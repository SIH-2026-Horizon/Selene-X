"""Unit and static contracts for the PostgreSQL/PostGIS persistence foundation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import Engine, Table
from sqlalchemy.orm import Session

from selene_service.domain.execution import (
    ExecutionState,
    InvalidExecutionTransition,
    allowed_execution_transitions,
    validate_execution_transition,
)
from selene_service.persistence import (
    ServiceDatabaseUrlError,
    atomic_unit_of_work,
    create_engine_from_settings,
    create_service_engine,
)
from selene_service.persistence.models import ApiKey, Artifact, Base, Product, Review, Run, RunEvent
from selene_service.persistence.repositories import (
    ConcurrentReviewSubmissionError,
    ConcurrentRunTransitionError,
    NewRun,
    ReservedEventDocumentFieldError,
    RunRepository,
)
from selene_service.persistence.validation import InvalidSha256
from selene_service.settings import ServiceEnvironment, ServiceSettings


def _new_run() -> NewRun:
    return NewRun(
        owner_subject_id=uuid4(),
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document={"matcher": "ncc"},
        parameters_sha256="a" * 64,
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


class _UpdateResult:
    def __init__(self, values: tuple[int, int] | None) -> None:
        self._values = values

    def one_or_none(self) -> tuple[int, int] | None:
        return self._values


class _TransitionSession(_RecordingSession):
    def __init__(self, update_values: tuple[int, int] | None) -> None:
        super().__init__()
        self.executed: list[object] = []
        self._update_values = update_values

    def execute(self, statement: object) -> _UpdateResult:
        self.executed.append(statement)
        return _UpdateResult(self._update_values)


class _ReviewUpdateResult:
    def __init__(self, next_sequence: int | None) -> None:
        self._next_sequence = next_sequence

    def scalar_one_or_none(self) -> int | None:
        return self._next_sequence


class _ReviewSession(_RecordingSession):
    def __init__(self, next_sequence: int | None) -> None:
        super().__init__()
        self.executed: list[object] = []
        self._next_sequence = next_sequence

    def execute(self, statement: object) -> _ReviewUpdateResult:
        self.executed.append(statement)
        return _ReviewUpdateResult(self._next_sequence)


class _Transaction:
    def __init__(self, session: _TransactionSession) -> None:
        self._session = session

    def __enter__(self) -> _Transaction:
        self._session.transaction_started = True
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> Literal[False]:
        self._session.rolled_back = exc_type is not None
        self._session.committed = exc_type is None
        return False


class _TransactionSession(_RecordingSession):
    def __init__(self) -> None:
        super().__init__()
        self.transaction_started = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def begin(self) -> _Transaction:
        return _Transaction(self)

    def close(self) -> None:
        self.closed = True


@pytest.mark.unit
def test_execution_state_graph_is_terminal_aware() -> None:
    assert allowed_execution_transitions(ExecutionState.CREATED) == frozenset(
        {ExecutionState.QUEUED, ExecutionState.CANCELLED}
    )
    validate_execution_transition(ExecutionState.QUEUED, ExecutionState.RUNNING)

    with pytest.raises(InvalidExecutionTransition, match="not allowed"):
        validate_execution_transition(ExecutionState.SUCCEEDED, ExecutionState.RUNNING)


@pytest.mark.unit
def test_new_run_and_created_event_are_staged_together_without_commit() -> None:
    session = _RecordingSession()
    run = RunRepository().record_new_run(session, _new_run())

    assert len(session.added) == 2
    event = cast("RunEvent", session.added[1])
    assert event.run_id == run.id
    assert event.event_type == "run.created"
    assert event.execution_state == ExecutionState.CREATED.value
    assert event.sequence == 1
    assert run.state_version == 0
    assert run.event_sequence == 1
    assert run.computed_verdict is None


@pytest.mark.unit
def test_execution_transition_stages_matching_event_without_assigning_verdict() -> None:
    session = _TransitionSession((1, 2))
    run = Run(
        id=uuid4(),
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
    )

    event = RunRepository().transition_execution_state(
        cast(Session, session), run, ExecutionState.QUEUED
    )

    assert run.execution_state == ExecutionState.QUEUED.value
    assert run.state_version == 1
    assert run.event_sequence == 2
    assert run.computed_verdict == "review"
    assert event.event_type == "run.execution_state_changed"
    assert event.sequence == 2
    assert event.event_document == {
        "from_execution_state": "created",
        "to_execution_state": "queued",
    }
    assert session.added == [event]
    assert len(session.executed) == 1


@pytest.mark.unit
def test_review_is_immutable_provenance_and_preserves_computed_verdict() -> None:
    session = _ReviewSession(2)
    run = Run(
        id=uuid4(),
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
        effective_disposition="pending",
    )
    actor_subject_id = uuid4()

    review = RunRepository().record_review(
        cast(Session, session),
        run,
        actor_subject_id=actor_subject_id,
        decision="accepted",
        reason_code="manual_geometry_check",
        note="Reviewed the persisted provenance.",
    )

    event = cast(RunEvent, session.added[1])
    assert isinstance(session.added[0], Review)
    assert review.source_computed_verdict == "review"
    assert run.computed_verdict == "review"
    assert run.effective_disposition == "accepted"
    assert run.event_sequence == 2
    assert event.event_type == "run.review_submitted"
    assert event.sequence == 2
    assert event.event_document["review_id"] == str(review.id)


@pytest.mark.unit
def test_review_losing_a_concurrent_event_race_stages_no_history() -> None:
    session = _ReviewSession(None)
    run = Run(
        id=uuid4(),
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
    )

    with pytest.raises(ConcurrentReviewSubmissionError, match="changed before"):
        RunRepository().record_review(
            cast(Session, session),
            run,
            actor_subject_id=uuid4(),
            decision="rejected",
            reason_code="geometry_failure",
            note="The registration geometry is not defensible.",
        )

    assert session.added == []


@pytest.mark.unit
def test_transition_rejects_authoritative_event_document_overrides() -> None:
    session = _TransitionSession((1, 2))
    run = Run(
        id=uuid4(),
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
    )

    with pytest.raises(ReservedEventDocumentFieldError, match="to_execution_state"):
        RunRepository().transition_execution_state(
            cast(Session, session),
            run,
            ExecutionState.QUEUED,
            event_document={"to_execution_state": "running"},
        )

    assert session.executed == []
    assert session.added == []
    assert run.execution_state == ExecutionState.CREATED.value


@pytest.mark.unit
def test_stale_transition_does_not_add_an_event_or_mutate_run() -> None:
    session = _TransitionSession(None)
    run = Run(
        id=uuid4(),
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
    )

    with pytest.raises(ConcurrentRunTransitionError, match="changed before"):
        RunRepository().transition_execution_state(
            cast(Session, session), run, ExecutionState.QUEUED
        )

    assert len(session.executed) == 1
    assert session.added == []
    assert run.execution_state == ExecutionState.CREATED.value
    assert run.state_version == 0
    assert run.event_sequence == 1


@pytest.mark.unit
@pytest.mark.parametrize("invalid_digest", ["A" * 64, "a" * 63, "g" * 64])
def test_new_run_rejects_noncanonical_sha256_at_the_command_boundary(invalid_digest: str) -> None:
    with pytest.raises(InvalidSha256, match="parameters_sha256"):
        NewRun(
            owner_subject_id=uuid4(),
            source_product_id=uuid4(),
            reference_product_id=uuid4(),
            parameters_document={"matcher": "ncc"},
            parameters_sha256=invalid_digest,
            code_revision="a" * 40,
            environment_fingerprint="b" * 64,
        )


@pytest.mark.unit
def test_orm_hash_fields_share_the_canonical_sha256_validation() -> None:
    with pytest.raises(InvalidSha256, match="sha256"):
        Artifact(
            id=uuid4(),
            run_id=uuid4(),
            kind="test",
            storage_uri="test://artifact",
            media_type="application/json",
            byte_size=1,
            sha256="A" * 64,
        )


@pytest.mark.unit
def test_explicit_atomic_unit_of_work_rolls_back_every_staged_write() -> None:
    session = _TransactionSession()

    with pytest.raises(RuntimeError, match="force rollback"):
        with atomic_unit_of_work(lambda: session) as transaction_session:
            RunRepository().record_new_run(transaction_session, _new_run())
            raise RuntimeError("force rollback")

    assert session.transaction_started
    assert session.rolled_back
    assert not session.committed
    assert session.closed
    assert len(session.added) == 2


@pytest.mark.unit
def test_persistence_metadata_declares_the_minimum_durable_entities() -> None:
    assert set(Base.metadata.tables) == {
        "subjects",
        "api_keys",
        "user_accounts",
        "user_sessions",
        "products",
        "runs",
        "run_stages",
        "artifacts",
        "metrics",
        "reviews",
        "idempotency_records",
        "knowledge_entities",
        "knowledge_edges",
        "run_events",
    }
    assert "token" not in {column.name.casefold() for column in ApiKey.__table__.columns}
    assert "key_digest" in ApiKey.__table__.columns
    footprint_type = cast(Geometry, Product.__table__.c.footprint.type)
    assert footprint_type.srid == -1
    assert "footprint_crs" in Product.__table__.columns
    assert Artifact.__table__.c.byte_size.type.__class__.__name__ == "BigInteger"
    assert "sequence" in RunEvent.__table__.columns
    run_events_table = cast(Table, RunEvent.__table__)
    assert any(
        constraint.name == "uq_run_events_run_sequence"
        for constraint in run_events_table.constraints
    )
    assert "ix_run_events_run_sequence" not in {index.name for index in run_events_table.indexes}


@pytest.mark.unit
def test_persistence_metadata_covers_every_durable_sha256_field() -> None:
    expected_constraints = {
        "products": "ck_products_manifest_sha256_format",
        "runs": "ck_runs_parameters_sha256_format",
        "run_stages": "ck_run_stages_input_sha256_format",
        "artifacts": "ck_artifacts_sha256_format",
        "idempotency_records": "ck_idempotency_request_digest_format",
    }

    for table_name, expected_constraint in expected_constraints.items():
        constraints = Base.metadata.tables[table_name].constraints
        assert any(constraint.name == expected_constraint for constraint in constraints)

    run_stage_constraints = {
        constraint.name for constraint in Base.metadata.tables["run_stages"].constraints
    }
    assert "ck_run_stages_output_sha256_format" in run_stage_constraints


@pytest.mark.unit
def test_engine_composition_does_not_connect_and_uses_typed_settings() -> None:
    settings = ServiceSettings.model_validate(
        {
            "environment": ServiceEnvironment.TEST,
            "database_url": "postgresql+psycopg://selene:password@127.0.0.1:5432/selene_test",
        }
    )

    engine = create_engine_from_settings(settings)
    try:
        assert isinstance(engine, Engine)
        assert engine.url.get_backend_name() == "postgresql"
        assert "Pool" in engine.pool.status()
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.parametrize(
    "database_url", ["sqlite://", "mysql+pymysql://service:password@db/selene"]
)
def test_engine_composition_rejects_non_postgresql_backends(database_url: str) -> None:
    with pytest.raises(ServiceDatabaseUrlError, match="PostgreSQL"):
        create_service_engine(database_url)


@pytest.mark.unit
def test_initial_migration_has_postgres_only_postgis_and_immutable_history_policy() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (
        root
        / "packages/selene_service/src/selene_service/persistence/migrations/versions"
        / "20260830_001_initial_service_state.py"
    ).read_text(encoding="utf-8")
    environment = (
        root / "packages/selene_service/src/selene_service/persistence/migrations/env.py"
    ).read_text(encoding="utf-8")
    hardening_migration = (
        root
        / "packages/selene_service/src/selene_service/persistence/migrations/versions"
        / "20260830_002_harden_run_history.py"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS postgis" in migration
    assert "trg_run_events_immutable" in migration
    assert "trg_reviews_immutable" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "selene_reject_history_mutation" in migration
    assert "uq_run_events_run_sequence" not in migration
    assert "ck_runs_parameters_sha256_format" not in migration
    assert 'down_revision = "20260830_001"' in hardening_migration
    assert "ORDER BY recorded_at ASC, id ASC" in hardening_migration
    assert "uq_run_events_run_sequence" in hardening_migration
    assert "ck_runs_parameters_sha256_format" in hardening_migration
    assert "ck_artifacts_sha256_format" in hardening_migration
    assert "ix_run_events_run_sequence" not in hardening_migration
    assert "SELENE_SERVICE_DATABASE_URL is required" in environment
    assert "compare_server_default=True" in environment
    assert "compare_type=True" in environment
    assert "sqlite" not in migration.casefold()
