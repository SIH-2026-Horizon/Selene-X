"""Dependency-injected API contracts for the DB-backed service routes."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from selene_service.api.dependencies import SubjectIdentity, get_db_session
from selene_service.api.errors import APIProblem, ConflictProblem
from selene_service.api.schemas import (
    KnowledgeEdgeCreateRequest,
    KnowledgeEntityCreateRequest,
    ProductCreateRequest,
    ReviewCreateRequest,
    RunCreateRequest,
)
from selene_service.api.services import (
    _cursor_page,
    cancel_run,
    crater_detail,
    crater_observations,
    create_knowledge_edge,
    create_knowledge_entity,
    create_product,
    create_run,
    get_run,
    knowledge_graph,
    query_knowledge,
    submit_review,
)
from selene_service.app import create_app
from selene_service.domain.execution import ExecutionState
from selene_service.persistence.models import (
    Artifact,
    IdempotencyRecord,
    KnowledgeEdge,
    KnowledgeEntity,
    Metric,
    Product,
    Review,
    Run,
    RunEvent,
    RunStage,
    Subject,
)
from selene_service.settings import ServiceEnvironment, ServiceSettings


class _EmptyScalars:
    def all(self) -> list[object]:
        return []


class _ReadOnlyEmptySession:
    """Enough of the session seam to prove empty routes need no database server."""

    def scalars(self, _: object) -> _EmptyScalars:
        return _EmptyScalars()

    def get(self, _: object, __: object) -> None:
        return None

    def close(self) -> None:
        return None


class _MissingProductSession(_ReadOnlyEmptySession):
    def __init__(self) -> None:
        self.subject = Subject(
            id=uuid4(),
            subject_name="local-loopback",
            subject_type="local",
            is_active=True,
        )

    def begin(self) -> Any:
        return nullcontext()

    def scalar(self, _: object) -> Subject:
        return self.subject

    def execute(self, _: object) -> None:
        return None


class _Values:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _TransitionResult:
    def __init__(self, state_version: int, event_sequence: int) -> None:
        self._values = (state_version, event_sequence)

    def one_or_none(self) -> tuple[int, int]:
        return self._values

    def scalar_one_or_none(self) -> int:
        return self._values[1]


class _MemorySession:
    """A narrow in-memory session seam for API transaction contract tests."""

    def __init__(self, products: list[Product]) -> None:
        self.subject = Subject(
            id=uuid4(),
            subject_name="local-loopback",
            subject_type="local",
            is_active=True,
        )
        self.products = {product.id: product for product in products}
        self.runs: dict[object, Run] = {}
        self.idempotency_records: list[IdempotencyRecord] = []
        self.knowledge_entities: dict[object, KnowledgeEntity] = {}
        self.knowledge_edges: list[KnowledgeEdge] = []
        self.added: list[object] = []

    def begin(self) -> Any:
        return nullcontext()

    def add(self, instance: object) -> None:
        self.added.append(instance)
        if isinstance(instance, Product):
            if instance.id is None:
                instance.id = uuid4()
            self.products[instance.id] = instance
        elif isinstance(instance, Run):
            self.runs[instance.id] = instance
        elif isinstance(instance, IdempotencyRecord):
            self.idempotency_records.append(instance)
        elif isinstance(instance, KnowledgeEntity):
            if instance.id is None:
                instance.id = uuid4()
            self.knowledge_entities[instance.id] = instance
        elif isinstance(instance, KnowledgeEdge):
            if instance.id is None:
                instance.id = uuid4()
            self.knowledge_edges.append(instance)

    def scalar(self, statement: object) -> object | None:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Subject:
            return self.subject
        if entity is IdempotencyRecord:
            return self.idempotency_records[0] if self.idempotency_records else None
        return None

    def get(self, model: object, record_id: object) -> object | None:
        if model is Product:
            return self.products.get(record_id)
        if model is Run:
            return self.runs.get(record_id)
        if model is KnowledgeEntity:
            return self.knowledge_entities.get(record_id)
        return None

    def execute(self, _: object) -> _TransitionResult:
        return _TransitionResult(1, 2)

    def flush(self) -> None:
        now = datetime.now(UTC)
        for run in self.runs.values():
            run.created_at = now
            run.updated_at = now
            if run.effective_disposition is None:
                run.effective_disposition = "pending"
        for product in self.products.values():
            if product.created_at is None:
                product.created_at = now
        for entity in self.knowledge_entities.values():
            if entity.created_at is None:
                entity.created_at = now
        for edge in self.knowledge_edges:
            if edge.created_at is None:
                edge.created_at = now
        for record in self.added:
            if isinstance(record, Review) and record.recorded_at is None:
                record.recorded_at = now

    def scalars(self, statement: object) -> _Values:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        values: list[object]
        if entity is KnowledgeEntity:
            values = list(self.knowledge_entities.values())
        elif entity is KnowledgeEdge:
            values = self.knowledge_edges
        else:
            values = []
        limit_clause = getattr(statement, "_limit_clause", None)
        limit = getattr(limit_clause, "value", None)
        if isinstance(limit, int):
            values = values[:limit]
        return _Values(values)

    def refresh(self, _: object) -> None:
        return None

    def close(self) -> None:
        return None


class _BoundedSemanticProjectionSession(_MemorySession):
    """A narrow query seam that models root paging and endpoint expansion."""

    def __init__(self) -> None:
        super().__init__([])
        self.root_entities: list[KnowledgeEntity] = []
        self.endpoint_entities: list[KnowledgeEntity] = []
        self._entity_query_count = 0

    def scalars(self, statement: object) -> _Values:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is KnowledgeEntity:
            self._entity_query_count += 1
            values: list[object] = (
                self.root_entities if self._entity_query_count == 1 else self.endpoint_entities
            )
        elif entity is KnowledgeEdge:
            values = self.knowledge_edges
        else:
            values = []
        limit_clause = getattr(statement, "_limit_clause", None)
        limit = getattr(limit_clause, "value", None)
        if isinstance(limit, int):
            values = values[:limit]
        return _Values(values)


class _GraphSession:
    def __init__(self, records: dict[object, list[object]], run: Run) -> None:
        self.records = records
        self.run = run
        self.statements: list[object] = []

    def get(self, model: object, record_id: object) -> object | None:
        if model is Run and record_id == self.run.id:
            return self.run
        return None

    def scalars(self, statement: object) -> _Values:
        self.statements.append(statement)
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return _Values(self.records.get(entity, []))


class _CursorPageSession:
    """Return the rows a PostgreSQL cursor query would expose on each page."""

    def __init__(self, pages: list[list[Product]]) -> None:
        self._pages = pages

    def scalars(self, _: object) -> _Values:
        return _Values(self._pages.pop(0))


def _test_app() -> FastAPI:
    return create_app(
        ServiceSettings.model_validate(
            {
                "bind_host": "127.0.0.1",
                "environment": ServiceEnvironment.TEST,
                "database_url": "postgresql+psycopg://selene:local@127.0.0.1:5432/selene_test",
            }
        )
    )


@pytest.mark.unit
def test_empty_persisted_collections_and_graph_use_an_overridden_session() -> None:
    app = _test_app()
    assert hasattr(app, "dependency_overrides")
    app.dependency_overrides[get_db_session] = _ReadOnlyEmptySession

    with TestClient(app) as client:
        products = client.get("/api/v1/products", params={"query": "stored-product", "limit": 10})
        runs = client.get("/api/v1/runs", params={"query": "stored-run", "limit": 10})
        graph = client.get("/api/v1/knowledge-graph")
        semantic_query = client.get("/api/v1/knowledge/query", params={"query": "Tycho"})

    assert products.status_code == 200
    assert products.json() == {"items": [], "next_cursor": None}
    assert runs.status_code == 200
    assert runs.json() == {"items": [], "next_cursor": None}
    assert graph.status_code == 200
    assert graph.json() == {"nodes": [], "edges": [], "child_collections_truncated": []}
    assert semantic_query.status_code == 200
    assert semantic_query.json() == {
        "nodes": [],
        "edges": [],
        "edges_truncated": False,
        "relationship_expansions": [],
    }


@pytest.mark.unit
def test_openapi_exposes_bounded_product_and_run_search_parameters() -> None:
    schema = _test_app().openapi()

    product_parameters = schema["paths"]["/api/v1/products"]["get"]["parameters"]
    run_parameters = schema["paths"]["/api/v1/runs"]["get"]["parameters"]

    assert any(parameter["name"] == "query" for parameter in product_parameters)
    assert any(parameter["name"] == "query" for parameter in run_parameters)


@pytest.mark.unit
def test_run_requires_persisted_source_and_reference_products() -> None:
    app = _test_app()
    app.dependency_overrides[get_db_session] = _MissingProductSession
    payload = {
        "source_product_id": str(uuid4()),
        "reference_product_id": str(uuid4()),
        "parameter_manifest": {"matcher": {"threshold": 0.75}},
        "algorithm_versions": {"matcher": "1.0.0"},
        "code_revision": "a" * 40,
        "environment_fingerprint": "b" * 64,
    }

    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=payload)

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
        }
    }


@pytest.mark.unit
def test_schema_rejections_use_the_error_envelope_before_database_access() -> None:
    app = _test_app()
    app.dependency_overrides[get_db_session] = _ReadOnlyEmptySession
    product_payload = {
        "product_identity": "M3-OBS-001",
        "payload_type": "m3",
        "payload_metadata": {"local_path": "/srv/selene/M3-OBS-001.img"},
        "validation_state": "validated",
        "validation_details": {"schema": "product-input-manifest.v1"},
        "manifest_sha256": "a" * 64,
    }

    with TestClient(app) as client:
        product_response = client.post("/api/v1/products", json=product_payload)
        review_response = client.post(
            f"/api/v1/runs/{uuid4()}/reviews",
            json={"decision": "rejected", "reason_code": "geometry_failure"},
        )

    assert product_response.status_code == 422
    assert review_response.status_code == 422
    assert product_response.json()["error"]["code"] == "validation_error"
    assert review_response.json()["error"]["code"] == "validation_error"


@pytest.mark.unit
def test_openapi_advertises_the_versioned_persisted_api() -> None:
    app = _test_app()
    schema = app.openapi()

    assert "/api/v1/openapi.json" == app.openapi_url
    assert "/api/v1/products" in schema["paths"]
    assert "/api/v1/runs" in schema["paths"]
    assert "/api/v1/runs/{run_id}/reviews" in schema["paths"]
    assert "/api/v1/knowledge-graph" in schema["paths"]


@pytest.mark.unit
def test_run_creation_replays_same_idempotency_key_and_conflicts_on_changed_body() -> None:
    owner_subject_id = uuid4()
    source = Product(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        product_identity="source",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="a" * 64,
    )
    reference = Product(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        product_identity="reference",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="b" * 64,
    )
    session = _MemorySession([source, reference])
    request = RunCreateRequest(
        source_product_id=source.id,
        reference_product_id=reference.id,
        parameter_manifest={"matcher": {"threshold": 0.75}},
        algorithm_versions={"matcher": "1.0.0"},
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")

    created = create_run(session, identity, request, "repeatable-create")
    persisted_run = session.runs[created.id]
    persisted_run.execution_state = "cancelled"
    persisted_run.effective_disposition = "rejected"
    replayed = create_run(session, identity, request, "repeatable-create")

    assert created.model_dump(mode="json") == replayed.model_dump(mode="json")
    assert replayed.execution_state == "created"
    record = session.idempotency_records[0]
    assert record.response_document is not None
    assert record.response_document["body"] == created.model_dump(mode="json")
    with pytest.raises(ConflictProblem, match="different request"):
        create_run(
            session,
            identity,
            request.model_copy(update={"code_revision": "c" * 40}),
            "repeatable-create",
        )


@pytest.mark.unit
def test_product_and_semantic_creates_replay_their_frozen_idempotent_responses() -> None:
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")
    product_session = _MemorySession([])
    product_request = ProductCreateRequest(
        product_identity="operator-product",
        payload_type="metadata-only",
        payload_metadata={"published_object_uri": "https://approved.example/object"},
        validation_state="validated",
        validation_details={"validator": "operator"},
        manifest_sha256="a" * 64,
    )

    created_product = create_product(product_session, identity, product_request, "product-retry")
    replayed_product = create_product(product_session, identity, product_request, "product-retry")

    assert replayed_product == created_product
    assert len(product_session.idempotency_records) == 1
    with pytest.raises(ConflictProblem, match="different request"):
        create_product(
            product_session,
            identity,
            product_request.model_copy(update={"product_identity": "different-product"}),
            "product-retry",
        )

    entity_session = _MemorySession([])
    entity_request = KnowledgeEntityCreateRequest(entity_type="TERRAIN", label="Stored terrain")
    created_entity = create_knowledge_entity(
        entity_session, identity, entity_request, "entity-retry"
    )
    replayed_entity = create_knowledge_entity(
        entity_session, identity, entity_request, "entity-retry"
    )

    assert replayed_entity == created_entity
    assert len(entity_session.idempotency_records) == 1
    with pytest.raises(ConflictProblem, match="different request"):
        create_knowledge_entity(
            entity_session,
            identity,
            entity_request.model_copy(update={"label": "Different stored terrain"}),
            "entity-retry",
        )


@pytest.mark.unit
def test_cancel_review_and_semantic_edge_replay_without_duplicate_history() -> None:
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")
    run = Run(
        id=uuid4(),
        owner_subject_id=uuid4(),
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document={"matching": "operator-supplied"},
        parameters_sha256="a" * 64,
        algorithm_versions={"matching": "operator"},
        model_versions={},
        execution_state="created",
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    cancel_session = _MemorySession([])
    cancel_session.runs[run.id] = run
    cancelled = cancel_run(cancel_session, identity, run.id, "cancel-retry")
    replayed_cancel = cancel_run(cancel_session, identity, run.id, "cancel-retry")

    assert replayed_cancel == cancelled
    assert len(cancel_session.idempotency_records) == 1
    another_run = Run(
        id=uuid4(),
        owner_subject_id=run.owner_subject_id,
        source_product_id=run.source_product_id,
        reference_product_id=run.reference_product_id,
        parameters_document=run.parameters_document,
        parameters_sha256=run.parameters_sha256,
        algorithm_versions=run.algorithm_versions,
        model_versions=run.model_versions,
        execution_state="created",
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision=run.code_revision,
        environment_fingerprint=run.environment_fingerprint,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    cancel_session.runs[another_run.id] = another_run
    with pytest.raises(ConflictProblem, match="different request"):
        cancel_run(cancel_session, identity, another_run.id, "cancel-retry")

    review_run = Run(
        id=uuid4(),
        owner_subject_id=run.owner_subject_id,
        source_product_id=run.source_product_id,
        reference_product_id=run.reference_product_id,
        parameters_document=run.parameters_document,
        parameters_sha256=run.parameters_sha256,
        algorithm_versions=run.algorithm_versions,
        model_versions=run.model_versions,
        execution_state="succeeded",
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
        effective_disposition="pending",
        code_revision=run.code_revision,
        environment_fingerprint=run.environment_fingerprint,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    review_session = _MemorySession([])
    review_session.runs[review_run.id] = review_run
    review_request = ReviewCreateRequest(decision="accepted", reason_code="operator-review")
    review = submit_review(review_session, identity, review_run.id, review_request, "review-retry")
    replayed_review = submit_review(
        review_session, identity, review_run.id, review_request, "review-retry"
    )

    assert replayed_review == review
    assert len([record for record in review_session.added if isinstance(record, Review)]) == 1
    with pytest.raises(ConflictProblem, match="different request"):
        submit_review(
            review_session,
            identity,
            review_run.id,
            ReviewCreateRequest(
                decision="rejected",
                reason_code="different-review",
                note="A persisted rationale.",
            ),
            "review-retry",
        )

    edge_session = _MemorySession([])
    source = create_knowledge_entity(
        edge_session,
        identity,
        KnowledgeEntityCreateRequest(entity_type="CRATER", label="Stored source"),
    )
    target = create_knowledge_entity(
        edge_session,
        identity,
        KnowledgeEntityCreateRequest(entity_type="OBSERVATION", label="Stored target"),
    )
    edge_request = KnowledgeEdgeCreateRequest(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relation_type="OBSERVED_IN",
    )
    edge = create_knowledge_edge(edge_session, identity, edge_request, "edge-retry")
    replayed_edge = create_knowledge_edge(edge_session, identity, edge_request, "edge-retry")

    assert replayed_edge == edge
    assert len(edge_session.knowledge_edges) == 1
    with pytest.raises(ConflictProblem, match="different request"):
        create_knowledge_edge(
            edge_session,
            identity,
            edge_request.model_copy(update={"relation_type": "DERIVED_FROM"}),
            "edge-retry",
        )


@pytest.mark.unit
def test_cursor_pagination_keeps_the_overflow_row_for_the_next_page() -> None:
    owner_subject_id = uuid4()
    timestamp = datetime(2026, 8, 30, tzinfo=UTC)
    products = [
        Product(
            id=uuid4(),
            owner_subject_id=owner_subject_id,
            product_identity=f"product-{index}",
            payload_type="m3",
            validation_state="validated",
            manifest_sha256=f"{index:x}" * 64,
            created_at=timestamp,
        )
        for index in range(1, 6)
    ]
    # The three result sets model the SQL predicate for no cursor, then the
    # cursor produced from product 2, then product 4.  Product 3 is deliberately
    # the first overflow row, so a cursor generated from it would duplicate it.
    session = _CursorPageSession(
        [
            products[:3],
            products[2:5],
            products[4:],
        ]
    )

    first, first_cursor = _cursor_page(
        cast(Session, session),
        select(Product),
        cast(ColumnElement[datetime], Product.created_at),
        cast(ColumnElement[UUID], Product.id),
        None,
        2,
    )
    second, second_cursor = _cursor_page(
        cast(Session, session),
        select(Product),
        cast(ColumnElement[datetime], Product.created_at),
        cast(ColumnElement[UUID], Product.id),
        first_cursor,
        2,
    )
    third, third_cursor = _cursor_page(
        cast(Session, session),
        select(Product),
        cast(ColumnElement[datetime], Product.created_at),
        cast(ColumnElement[UUID], Product.id),
        second_cursor,
        2,
    )

    returned_ids = [product.id for product in [*first, *second, *third]]
    assert returned_ids == [product.id for product in products]
    assert len(returned_ids) == len(set(returned_ids))
    assert third_cursor is None


@pytest.mark.unit
def test_legacy_run_serialization_marks_missing_parameter_manifest_unavailable() -> None:
    owner_subject_id = uuid4()
    session = _MemorySession([])
    run = Run(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document=None,
        parameters_sha256="c" * 64,
        algorithm_versions={"matcher": "legacy"},
        model_versions={},
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.runs[run.id] = run

    response = get_run(session, run.id)

    assert response.parameter_manifest is None
    assert response.parameter_manifest_available is False


@pytest.mark.unit
def test_cancellation_uses_lifecycle_repository_and_never_assigns_science() -> None:
    owner_subject_id = uuid4()
    source = Product(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        product_identity="source",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="a" * 64,
    )
    reference = Product(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        product_identity="reference",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="b" * 64,
    )
    session = _MemorySession([source, reference])
    run = Run(
        id=uuid4(),
        owner_subject_id=session.subject.id,
        source_product_id=source.id,
        reference_product_id=reference.id,
        parameters_document={"matcher": "ncc"},
        parameters_sha256="c" * 64,
        algorithm_versions={"matcher": "1.0.0"},
        model_versions={},
        execution_state=ExecutionState.CREATED.value,
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.runs[run.id] = run

    cancelled = cancel_run(
        session,
        SubjectIdentity(subject_name="local-loopback", subject_type="local"),
        run.id,
    )

    assert cancelled.execution_state == "cancelled"
    assert cancelled.computed_verdict is None
    assert any(isinstance(item, RunEvent) for item in session.added)


@pytest.mark.unit
def test_graph_uses_persisted_fk_provenance_without_scientific_fixtures() -> None:
    subject = Subject(id=uuid4(), subject_name="operator", subject_type="local", is_active=True)
    source = Product(
        id=uuid4(),
        owner_subject_id=subject.id,
        product_identity="source",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="a" * 64,
    )
    reference = Product(
        id=uuid4(),
        owner_subject_id=subject.id,
        product_identity="reference",
        payload_type="m3",
        validation_state="validated",
        manifest_sha256="b" * 64,
    )
    run = Run(
        id=uuid4(),
        owner_subject_id=subject.id,
        source_product_id=source.id,
        reference_product_id=reference.id,
        parameters_document={"matcher": "ncc"},
        parameters_sha256="c" * 64,
        algorithm_versions={"matcher": "1.0.0"},
        model_versions={},
        execution_state="created",
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )
    stage = RunStage(
        id=uuid4(),
        run_id=run.id,
        stage_name="matching",
        stage_ordinal=1,
        attempt=1,
        execution_state="succeeded",
    )
    artifact = Artifact(
        id=uuid4(),
        run_id=run.id,
        run_stage_id=stage.id,
        kind="metric-report",
        storage_uri="s3://selene/reports/1",
        media_type="application/json",
        byte_size=12,
        sha256="d" * 64,
        validated_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    artifacts = [
        artifact,
        *[
            Artifact(
                id=uuid4(),
                run_id=run.id,
                kind="bounded-persisted-artifact",
                storage_uri=f"s3://selene/reports/{index + 2}",
                media_type="application/json",
                byte_size=12,
                sha256="d" * 64,
                validated_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
            for index in range(50)
        ],
    ]
    metric = Metric(
        id=uuid4(),
        run_id=run.id,
        report_kind="quality",
        report_version="1",
        report_document={},
        indexed_fields={},
    )
    review = Review(
        id=uuid4(),
        run_id=run.id,
        actor_subject_id=subject.id,
        decision="accepted",
        reason_code="reviewed",
    )
    session = _GraphSession(
        {
            Subject: [subject],
            Product: [source, reference],
            RunStage: [stage],
            Artifact: artifacts,
            Metric: [metric],
            Review: [review],
        },
        run,
    )

    graph = knowledge_graph(session, center_type="run", center_id=run.id, cursor=None, limit=50)

    node_ids = {node.id for node in graph.nodes}
    relations = {edge.relation for edge in graph.edges}
    assert {
        f"run:{run.id}",
        f"product:{source.id}",
        f"stage:{stage.id}",
        f"artifact:{artifact.id}",
    } <= node_ids
    assert {
        "uses_source",
        "uses_reference",
        "part_of",
        "produced_by",
        "reported_for",
        "reviews",
    } <= relations
    assert [(item.collection, item.limit) for item in graph.child_collections_truncated] == [
        ("artifacts", 50)
    ]

    child_statements = [
        statement
        for statement in session.statements
        if getattr(statement, "column_descriptions", [])
        and statement.column_descriptions[0].get("entity")
        in {RunStage, Artifact, Metric, Review}
    ]
    assert len(child_statements) == 4
    assert all(
        getattr(getattr(statement, "_limit_clause", None), "value", None) == 51
        for statement in child_statements
    )


@pytest.mark.unit
def test_semantic_entities_edges_and_crater_observations_are_durable_data() -> None:
    session = _MemorySession([])
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")
    crater = create_knowledge_entity(
        session,
        identity,
        KnowledgeEntityCreateRequest(
            entity_type="CRATER",
            external_id="CRATER-TYCHO",
            label="Tycho",
            properties={"diameter_km": 85},
        ),
    )
    observation = create_knowledge_entity(
        session,
        identity,
        KnowledgeEntityCreateRequest(
            entity_type="OBSERVATION",
            external_id="OBS-001",
            label="OHRC observation 001",
            properties={"payload": "OHRC"},
        ),
    )
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

    detail = crater_detail(session, crater.id)
    observations = crater_observations(session, crater.id, cursor=None, limit=50)

    assert detail.properties == {"diameter_km": 85}
    assert edge.relation_type == "OBSERVED_IN"
    assert {node.entity_type for node in observations.nodes} >= {"CRATER", "OBSERVATION"}
    assert [stored_edge.relation_type for stored_edge in observations.edges] == ["OBSERVED_IN"]


@pytest.mark.unit
def test_semantic_query_bounds_edges_and_includes_every_edge_endpoint() -> None:
    session = _BoundedSemanticProjectionSession()
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")
    roots = [
        create_knowledge_entity(
            session,
            identity,
            KnowledgeEntityCreateRequest(
                entity_type="CRATER",
                label=f"Persisted root {index}",
            ),
        )
        for index in range(2)
    ]
    counterparts = [
        create_knowledge_entity(
            session,
            identity,
            KnowledgeEntityCreateRequest(
                entity_type="OBSERVATION",
                label=f"Persisted counterpart {index}",
            ),
        )
        for index in range(3)
    ]
    for counterpart in counterparts:
        create_knowledge_edge(
            session,
            identity,
            KnowledgeEdgeCreateRequest(
                source_entity_id=roots[0].id,
                target_entity_id=counterpart.id,
                relation_type="OBSERVED_IN",
            ),
        )

    session.root_entities = [session.knowledge_entities[root.id] for root in roots]
    session.endpoint_entities = [
        session.knowledge_entities[roots[0].id],
        session.knowledge_entities[counterparts[0].id],
    ]

    graph = query_knowledge(
        session,
        query="Persisted root",
        entity_type="CRATER",
        relation_type="OBSERVED_IN",
        cursor=None,
        limit=1,
    )

    node_ids = {node.id for node in graph.nodes}
    assert len(graph.edges) == 1
    assert len(graph.nodes) <= 2
    assert graph.next_cursor is not None
    assert graph.edges_truncated is True
    assert [expansion.entity_id for expansion in graph.relationship_expansions] == [roots[0].id]
    assert graph.relationship_expansions[0].neighbors_path.endswith(
        f"/knowledge/entities/{roots[0].id}/neighbors"
    )
    assert all(
        edge.source_entity_id in node_ids and edge.target_entity_id in node_ids
        for edge in graph.edges
    )


@pytest.mark.unit
def test_reviews_require_a_final_persisted_scientific_result() -> None:
    owner_subject_id = uuid4()
    run = Run(
        id=uuid4(),
        owner_subject_id=owner_subject_id,
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document={"matching": "operator-supplied"},
        parameters_sha256="a" * 64,
        algorithm_versions={"matching": "operator"},
        model_versions={},
        execution_state="created",
        state_version=0,
        event_sequence=1,
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )
    session = _MemorySession([])
    session.runs[run.id] = run

    with pytest.raises(ConflictProblem, match="succeeded run"):
        submit_review(
            session,
            SubjectIdentity(subject_name="local-loopback", subject_type="local"),
            run.id,
            ReviewCreateRequest(decision="accepted", reason_code="operator-review"),
        )


@pytest.mark.unit
def test_submit_review_rejects_a_session_caller_without_reviewer_or_admin_role() -> None:
    run = Run(
        id=uuid4(),
        owner_subject_id=uuid4(),
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document={"matching": "operator-supplied"},
        parameters_sha256="a" * 64,
        algorithm_versions={"matching": "operator"},
        model_versions={},
        execution_state="succeeded",
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )
    session = _MemorySession([])
    session.runs[run.id] = run
    identity = SubjectIdentity(
        subject_name="user:analyst.one",
        subject_type="user",
        role="analyst",
        user_account_id=uuid4(),
    )

    with pytest.raises(APIProblem) as problem:
        submit_review(
            session,
            identity,
            run.id,
            ReviewCreateRequest(decision="accepted", reason_code="operator-review"),
        )

    assert problem.value.status_code == 403


@pytest.mark.unit
def test_submit_review_allows_a_session_caller_with_reviewer_role() -> None:
    run = Run(
        id=uuid4(),
        owner_subject_id=uuid4(),
        source_product_id=uuid4(),
        reference_product_id=uuid4(),
        parameters_document={"matching": "operator-supplied"},
        parameters_sha256="a" * 64,
        algorithm_versions={"matching": "operator"},
        model_versions={},
        execution_state="succeeded",
        state_version=0,
        event_sequence=1,
        computed_verdict="review",
        effective_disposition="pending",
        code_revision="a" * 40,
        environment_fingerprint="b" * 64,
    )
    session = _MemorySession([])
    session.runs[run.id] = run
    identity = SubjectIdentity(
        subject_name="user:reviewer.one",
        subject_type="user",
        role="reviewer",
        user_account_id=uuid4(),
    )

    review = submit_review(
        session,
        identity,
        run.id,
        ReviewCreateRequest(decision="accepted", reason_code="operator-review"),
    )

    assert review.decision == "accepted"
