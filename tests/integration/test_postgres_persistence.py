"""Opt-in real PostgreSQL/PostGIS verification for service persistence."""

from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from selene_service.api.dependencies import SubjectIdentity
from selene_service.api.errors import ConflictProblem
from selene_service.api.schemas import (
    KnowledgeEdgeCreateRequest,
    KnowledgeEntityCreateRequest,
    RunCreateRequest,
)
from selene_service.api.services import (
    cancel_run,
    create_knowledge_edge,
    create_knowledge_entity,
    create_run,
    get_run,
    knowledge_neighbors,
    query_knowledge,
)
from selene_service.domain.execution import ExecutionState
from selene_service.persistence.models import (
    IdempotencyRecord,
    KnowledgeEdge,
    KnowledgeEntity,
    Product,
    Review,
    Run,
    RunEvent,
    Subject,
)
from selene_service.persistence.repositories import (
    ConcurrentRunTransitionError,
    NewRun,
    ReservedEventDocumentFieldError,
    RunRepository,
)
from selene_service.persistence.session import atomic_unit_of_work, create_service_engine

pytestmark = pytest.mark.integration


def _test_database_url() -> str:
    database_url = os.environ.get("SELENE_SERVICE_TEST_DATABASE_URL")
    if database_url is None or not database_url.strip():
        pytest.skip(
            "SELENE_SERVICE_TEST_DATABASE_URL is not set; "
            "real PostgreSQL/PostGIS verification is opt-in.",
            allow_module_level=True,
        )
    return database_url


_TEST_DATABASE_URL = _test_database_url()


@dataclass(frozen=True, slots=True)
class _RunDependencies:
    owner_subject_id: UUID
    source_product_id: UUID
    reference_product_id: UUID


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    return Config(str(root / "packages/selene_service/alembic.ini"))


@contextmanager
def _alembic_commands() -> Generator[Config, None, None]:
    previous_url = os.environ.get("SELENE_SERVICE_DATABASE_URL")
    os.environ["SELENE_SERVICE_DATABASE_URL"] = _TEST_DATABASE_URL
    try:
        yield _alembic_config()
    finally:
        if previous_url is None:
            del os.environ["SELENE_SERVICE_DATABASE_URL"]
        else:
            os.environ["SELENE_SERVICE_DATABASE_URL"] = previous_url


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    with _alembic_commands() as configuration:
        command.upgrade(configuration, "head")
        # This is the real PostgreSQL metadata-drift gate: it asks Alembic to
        # autogenerate against the upgraded database and fails on any diff.
        command.check(configuration)

    database_engine = create_service_engine(_TEST_DATABASE_URL)
    yield database_engine
    database_engine.dispose()


def _run_dependencies(engine: Engine) -> _RunDependencies:
    owner_subject_id = uuid4()
    source_product_id = uuid4()
    reference_product_id = uuid4()

    with Session(engine) as session:
        with session.begin():
            session.add(
                Subject(
                    id=owner_subject_id,
                    subject_type="test",
                    subject_name=f"postgres-test-{owner_subject_id}",
                )
            )
            session.add_all(
                [
                    Product(
                        id=source_product_id,
                        owner_subject_id=owner_subject_id,
                        product_identity=f"source-{source_product_id}",
                        payload_type="test",
                        validation_state="validated",
                        manifest_sha256="a" * 64,
                    ),
                    Product(
                        id=reference_product_id,
                        owner_subject_id=owner_subject_id,
                        product_identity=f"reference-{reference_product_id}",
                        payload_type="test",
                        validation_state="validated",
                        manifest_sha256="b" * 64,
                    ),
                ]
            )

    return _RunDependencies(owner_subject_id, source_product_id, reference_product_id)


def _new_run_command(dependencies: _RunDependencies) -> NewRun:
    return NewRun(
        owner_subject_id=dependencies.owner_subject_id,
        source_product_id=dependencies.source_product_id,
        reference_product_id=dependencies.reference_product_id,
        parameters_document={"matcher": "ncc"},
        parameters_sha256="c" * 64,
        code_revision="d" * 40,
        environment_fingerprint="e" * 64,
    )


def _subject_identity(dependencies: _RunDependencies) -> SubjectIdentity:
    return SubjectIdentity(
        subject_name=f"postgres-test-{dependencies.owner_subject_id}",
        subject_type="test",
    )


def _run_create_request(dependencies: _RunDependencies, *, code_revision: str) -> RunCreateRequest:
    return RunCreateRequest(
        source_product_id=dependencies.source_product_id,
        reference_product_id=dependencies.reference_product_id,
        parameter_manifest={"matcher": {"threshold": 0.75}},
        algorithm_versions={"matcher": "1.0.0"},
        model_versions={},
        code_revision=code_revision,
        environment_fingerprint="e" * 64,
    )


def _record_run(engine: Engine) -> Run:
    dependencies = _run_dependencies(engine)
    with atomic_unit_of_work(lambda: Session(engine, expire_on_commit=False)) as session:
        return RunRepository().record_new_run(session, _new_run_command(dependencies))


def _history_records(engine: Engine) -> tuple[UUID, UUID]:
    run = _record_run(engine)
    review_id = uuid4()
    with Session(engine) as session:
        with session.begin():
            session.add(
                Review(
                    id=review_id,
                    run_id=run.id,
                    actor_subject_id=run.owner_subject_id,
                    decision="review",
                    reason_code="integration_test",
                )
            )

    with Session(engine) as session:
        event_id = session.scalar(
            select(RunEvent.id).where(RunEvent.run_id == run.id, RunEvent.sequence == 1)
        )
    assert event_id is not None
    return event_id, review_id


@pytest.mark.integration
@pytest.mark.parametrize("history_kind", ["run_events", "reviews"])
def test_history_rows_reject_raw_sql_updates_and_deletes(
    engine: Engine,
    history_kind: str,
) -> None:
    event_id, review_id = _history_records(engine)
    if history_kind == "run_events":
        row_id = event_id
        update_statement = text("UPDATE run_events SET event_type = 'tampered' WHERE id = :row_id")
        delete_statement = text("DELETE FROM run_events WHERE id = :row_id")
    else:
        row_id = review_id
        update_statement = text("UPDATE reviews SET decision = 'tampered' WHERE id = :row_id")
        delete_statement = text("DELETE FROM reviews WHERE id = :row_id")

    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(update_statement, {"row_id": row_id})

    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(delete_statement, {"row_id": row_id})


@pytest.mark.integration
def test_repository_pairs_run_and_created_event_and_rolls_back_together(engine: Engine) -> None:
    dependencies = _run_dependencies(engine)
    repository = RunRepository()
    aborted_run_id: UUID | None = None

    with pytest.raises(RuntimeError, match="force rollback"):
        with atomic_unit_of_work(lambda: Session(engine, expire_on_commit=False)) as session:
            aborted_run = repository.record_new_run(session, _new_run_command(dependencies))
            aborted_run_id = aborted_run.id
            raise RuntimeError("force rollback")

    assert aborted_run_id is not None
    with Session(engine) as session:
        assert session.get(Run, aborted_run_id) is None
        assert session.scalar(select(RunEvent.id).where(RunEvent.run_id == aborted_run_id)) is None

    with atomic_unit_of_work(lambda: Session(engine, expire_on_commit=False)) as session:
        run = repository.record_new_run(session, _new_run_command(dependencies))

    with Session(engine) as session:
        events = list(
            session.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.sequence)
            )
        )
        persisted_run = session.get(Run, run.id)

    assert persisted_run is not None
    assert persisted_run.state_version == 0
    assert persisted_run.event_sequence == 1
    assert [(event.event_type, event.sequence) for event in events] == [("run.created", 1)]


@pytest.mark.integration
def test_transition_uses_optimistic_control_and_allocates_ordered_event(engine: Engine) -> None:
    run = _record_run(engine)
    repository = RunRepository()
    first_session = Session(engine, expire_on_commit=False)
    stale_session = Session(engine, expire_on_commit=False)
    try:
        with first_session.begin():
            current_run = first_session.get(Run, run.id)
        with stale_session.begin():
            stale_run = stale_session.get(Run, run.id)

        assert current_run is not None
        assert stale_run is not None
        with pytest.raises(ReservedEventDocumentFieldError, match="to_execution_state"):
            with first_session.begin():
                repository.transition_execution_state(
                    first_session,
                    current_run,
                    ExecutionState.QUEUED,
                    event_document={"to_execution_state": "running"},
                )

        with first_session.begin():
            transition_event = repository.transition_execution_state(
                first_session,
                current_run,
                ExecutionState.QUEUED,
                event_document={"operator_note": "queued for integration"},
            )

        assert transition_event.sequence == 2
        with pytest.raises(ConcurrentRunTransitionError, match="changed before"):
            with stale_session.begin():
                repository.transition_execution_state(
                    stale_session,
                    stale_run,
                    ExecutionState.QUEUED,
                )
    finally:
        first_session.close()
        stale_session.close()

    with Session(engine) as session:
        persisted_run = session.get(Run, run.id)
        events = list(
            session.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.sequence)
            )
        )

    assert persisted_run is not None
    assert persisted_run.execution_state == ExecutionState.QUEUED.value
    assert persisted_run.state_version == 1
    assert persisted_run.event_sequence == 2
    assert [(event.event_type, event.sequence) for event in events] == [
        ("run.created", 1),
        ("run.execution_state_changed", 2),
    ]
    assert events[1].event_document == {
        "from_execution_state": "created",
        "to_execution_state": "queued",
        "operator_note": "queued for integration",
    }


@pytest.mark.integration
def test_database_rejects_noncanonical_run_and_artifact_sha256(engine: Engine) -> None:
    dependencies = _run_dependencies(engine)

    with pytest.raises(IntegrityError, match="ck_runs_parameters_sha256_format"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO runs (
                        id, owner_subject_id, source_product_id, reference_product_id,
                        parameters_sha256, code_revision, environment_fingerprint
                    ) VALUES (
                        :id, :owner_subject_id, :source_product_id, :reference_product_id,
                        :parameters_sha256, :code_revision, :environment_fingerprint
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "owner_subject_id": dependencies.owner_subject_id,
                    "source_product_id": dependencies.source_product_id,
                    "reference_product_id": dependencies.reference_product_id,
                    "parameters_sha256": "A" * 64,
                    "code_revision": "d" * 40,
                    "environment_fingerprint": "e" * 64,
                },
            )

    run = _record_run(engine)
    now = datetime.now(UTC)

    with pytest.raises(IntegrityError, match="ck_artifacts_sha256_format"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO artifacts (
                        id, run_id, kind, storage_uri, media_type, byte_size, sha256,
                        validated_at, published_at
                    ) VALUES (
                        :id, :run_id, :kind, :storage_uri, :media_type, :byte_size, :sha256,
                        :validated_at, :published_at
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "run_id": run.id,
                    "kind": "integration-test",
                    "storage_uri": f"test://artifact/{uuid4()}",
                    "media_type": "application/json",
                    "byte_size": 1,
                    "sha256": "A" * 64,
                    "validated_at": now,
                    "published_at": now,
                },
            )


@pytest.mark.integration
def test_upgrade_from_initial_revision_backfills_order_and_supports_repository(
    engine: Engine,
) -> None:
    """Exercise the forward path from an already-applied initial revision."""

    owner_subject_id = uuid4()
    source_product_id = uuid4()
    reference_product_id = uuid4()
    run_id = uuid4()
    first_event_id = UUID("00000000-0000-0000-0000-000000000001")
    second_event_id = UUID("00000000-0000-0000-0000-000000000002")
    tied_timestamp = datetime(2026, 8, 30, tzinfo=UTC)

    # The supplied URL is explicitly a test database.  Start it at the
    # historical revision, seed legacy rows, then exercise the actual upgrade.
    engine.dispose()
    with _alembic_commands() as configuration:
        command.downgrade(configuration, "base")
        command.upgrade(configuration, "20260830_001")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO subjects (id, subject_type, subject_name)
                VALUES (:id, 'test', :subject_name)
                """
            ),
            {"id": owner_subject_id, "subject_name": f"upgrade-test-{owner_subject_id}"},
        )
        for product_id, product_identity, manifest_sha256 in (
            (source_product_id, "legacy-source", "a" * 64),
            (reference_product_id, "legacy-reference", "b" * 64),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO products (
                        id, owner_subject_id, product_identity, payload_type,
                        validation_state, manifest_sha256
                    ) VALUES (
                        :id, :owner_subject_id, :product_identity, 'test',
                        'validated', :manifest_sha256
                    )
                    """
                ),
                {
                    "id": product_id,
                    "owner_subject_id": owner_subject_id,
                    "product_identity": product_identity,
                    "manifest_sha256": manifest_sha256,
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO runs (
                    id, owner_subject_id, source_product_id, reference_product_id,
                    parameters_sha256, code_revision, environment_fingerprint
                ) VALUES (
                    :id, :owner_subject_id, :source_product_id, :reference_product_id,
                    :parameters_sha256, :code_revision, :environment_fingerprint
                )
                """
            ),
            {
                "id": run_id,
                "owner_subject_id": owner_subject_id,
                "source_product_id": source_product_id,
                "reference_product_id": reference_product_id,
                "parameters_sha256": "c" * 64,
                "code_revision": "d" * 40,
                "environment_fingerprint": "e" * 64,
            },
        )
        for event_id, event_type in (
            (first_event_id, "run.created"),
            (second_event_id, "run.legacy_note"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO run_events (id, run_id, event_type, recorded_at)
                    VALUES (:id, :run_id, :event_type, :recorded_at)
                    """
                ),
                {
                    "id": event_id,
                    "run_id": run_id,
                    "event_type": event_type,
                    "recorded_at": tied_timestamp,
                },
            )

    with _alembic_commands() as configuration:
        command.upgrade(configuration, "head")
        command.check(configuration)

    with engine.connect() as connection:
        event_columns = set(
            connection.scalars(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'run_events'
                    """
                )
            )
        )
        constraint_names = set(
            connection.scalars(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'run_events'::regclass
                    """
                )
            )
        )
        index_names = set(
            connection.scalars(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = 'run_events'
                    """
                )
            )
        )

    assert "sequence" in event_columns
    assert "uq_run_events_run_sequence" in constraint_names
    assert "ix_run_events_run_sequence" not in index_names

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            migrated_run = session.get(Run, run_id)
            assert migrated_run is not None
            assert migrated_run.state_version == 0
            assert migrated_run.event_sequence == 2
            transition_event = RunRepository().transition_execution_state(
                session,
                migrated_run,
                ExecutionState.QUEUED,
            )

    with Session(engine) as session:
        events = list(
            session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence)
            )
        )
        persisted_run = session.get(Run, run_id)
        legacy_response = get_run(session, run_id)

    assert [(event.id, event.sequence) for event in events] == [
        (first_event_id, 1),
        (second_event_id, 2),
        (transition_event.id, 3),
    ]
    assert persisted_run is not None
    assert persisted_run.event_sequence == 3
    assert persisted_run.state_version == 1
    assert persisted_run.parameters_document is None
    assert legacy_response.parameter_manifest is None
    assert legacy_response.parameter_manifest_available is False


@pytest.mark.integration
def test_concurrent_first_subject_upsert_creates_one_subject_without_conflict(
    engine: Engine,
) -> None:
    """Concurrent first requests must converge on one freshly-created subject."""

    dependencies = _run_dependencies(engine)
    identity = SubjectIdentity(subject_name=f"first-subject-{uuid4()}", subject_type="external")
    request = _run_create_request(dependencies, code_revision="a" * 40)
    barrier = Barrier(2)

    def create_from_new_session() -> UUID:
        with Session(engine, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            return create_run(session, identity, request, None).owner_subject_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_from_new_session) for _ in range(2)]
        owner_subject_ids = [future.result(timeout=20) for future in futures]

    with Session(engine) as session:
        subjects = list(
            session.scalars(select(Subject).where(Subject.subject_name == identity.subject_name))
        )

    assert owner_subject_ids[0] == owner_subject_ids[1]
    assert len(subjects) == 1
    assert subjects[0].id == owner_subject_ids[0]


@pytest.mark.integration
def test_api_idempotency_replays_frozen_create_response_after_lifecycle_writes(
    engine: Engine,
) -> None:
    """A same-key request must not reload mutable state from its run row."""

    dependencies = _run_dependencies(engine)
    identity = _subject_identity(dependencies)
    request = _run_create_request(dependencies, code_revision="a" * 40)
    idempotency_key = f"create-{uuid4()}"

    with Session(engine, expire_on_commit=False) as session:
        created = create_run(session, identity, request, idempotency_key)

    with Session(engine, expire_on_commit=False) as session:
        cancelled = cancel_run(session, identity, created.id)
        assert cancelled.execution_state == ExecutionState.CANCELLED.value

    with Session(engine, expire_on_commit=False) as session:
        replayed = create_run(session, identity, request, idempotency_key)
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.subject_id == dependencies.owner_subject_id,
                IdempotencyRecord.operation == "runs.create",
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        )

    assert replayed.model_dump(mode="json") == created.model_dump(mode="json")
    assert replayed.execution_state == ExecutionState.CREATED.value
    assert record is not None
    assert record.response_document is not None
    assert record.response_document["body"] == created.model_dump(mode="json")

    changed_request = request.model_copy(update={"code_revision": "f" * 40})
    with Session(engine, expire_on_commit=False) as session:
        with pytest.raises(ConflictProblem, match="different request"):
            create_run(session, identity, changed_request, idempotency_key)

    with Session(engine) as session:
        persisted_run = session.get(Run, created.id)

    assert persisted_run is not None
    assert persisted_run.execution_state == ExecutionState.CANCELLED.value


@pytest.mark.integration
def test_semantic_entities_and_edges_persist_reopen_and_project_neighbors(engine: Engine) -> None:
    """Semantic graph APIs project only rows that a caller explicitly stored."""

    dependencies = _run_dependencies(engine)
    identity = _subject_identity(dependencies)
    crater_external_id = f"CRATER-{uuid4()}"
    observation_external_id = f"OBSERVATION-{uuid4()}"

    with Session(engine, expire_on_commit=False) as session:
        crater = create_knowledge_entity(
            session,
            identity,
            KnowledgeEntityCreateRequest(
                entity_type="CRATER",
                external_id=crater_external_id,
                label="Persisted crater",
                properties={"diameter_km": 12.5},
            ),
        )

    with Session(engine, expire_on_commit=False) as session:
        observation = create_knowledge_entity(
            session,
            identity,
            KnowledgeEntityCreateRequest(
                entity_type="OBSERVATION",
                external_id=observation_external_id,
                label="Persisted observation",
                properties={"payload": "OHRC"},
            ),
        )

    with Session(engine, expire_on_commit=False) as session:
        edge = create_knowledge_edge(
            session,
            identity,
            KnowledgeEdgeCreateRequest(
                source_entity_id=crater.id,
                target_entity_id=observation.id,
                relation_type="OBSERVED_IN",
                properties={"captured_at": "2026-08-30T00:00:00Z"},
            ),
        )

    with Session(engine, expire_on_commit=False) as session:
        terrain = create_knowledge_entity(
            session,
            identity,
            KnowledgeEntityCreateRequest(
                entity_type="TERRAIN",
                external_id=f"TERRAIN-{uuid4()}",
                label="Persisted terrain",
                properties={"class": "highlands"},
            ),
        )
        create_knowledge_edge(
            session,
            identity,
            KnowledgeEdgeCreateRequest(
                source_entity_id=crater.id,
                target_entity_id=terrain.id,
                relation_type="LOCATED_IN",
                properties={},
            ),
        )

    with Session(engine) as session:
        persisted_crater = session.get(KnowledgeEntity, crater.id)
        persisted_edge = session.get(KnowledgeEdge, edge.id)
        graph = knowledge_neighbors(
            session,
            crater.id,
            cursor=None,
            limit=50,
            relation_type="OBSERVED_IN",
        )
        filtered = query_knowledge(
            session,
            query=None,
            entity_type=None,
            relation_type="OBSERVED_IN",
            cursor=None,
            limit=50,
        )

    assert persisted_crater is not None
    assert persisted_crater.external_id == crater_external_id
    assert persisted_crater.properties == {"diameter_km": 12.5}
    assert persisted_edge is not None
    assert persisted_edge.relation_type == "OBSERVED_IN"
    assert {node.id for node in graph.nodes} == {crater.id, observation.id}
    assert [(relation.source_entity_id, relation.target_entity_id) for relation in graph.edges] == [
        (crater.id, observation.id)
    ]
    assert {node.id for node in filtered.nodes} == {crater.id, observation.id}
    assert {relation.relation_type for relation in filtered.edges} == {"OBSERVED_IN"}
