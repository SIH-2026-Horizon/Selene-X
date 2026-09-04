"""Database-backed application services for the thin v1 HTTP routers.

This module owns query composition and transactional coordination only.  It
does not dispatch workers, read imagery, or calculate scientific results.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar, cast
from uuid import UUID

from geoalchemy2 import WKTElement
from geoalchemy2.elements import WKBElement
from pydantic import BaseModel, JsonValue
from sqlalchemy import Select, String, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from selene_service.api.dependencies import SubjectIdentity
from selene_service.api.errors import (
    APIProblem,
    BadRequestProblem,
    ConflictProblem,
    NotFoundProblem,
)
from selene_service.api.schemas import (
    ArtifactPageResponse,
    ArtifactResponse,
    GraphCollectionTruncationResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    KnowledgeEdgeCreateRequest,
    KnowledgeEdgePageResponse,
    KnowledgeEdgeResponse,
    KnowledgeEntityCreateRequest,
    KnowledgeEntityPageResponse,
    KnowledgeEntityResponse,
    KnowledgeGraphResponse,
    MetricPageResponse,
    MetricResponse,
    ProductCreateRequest,
    ProductPageResponse,
    ProductResponse,
    ReviewCreateRequest,
    ReviewPageResponse,
    ReviewResponse,
    RunCreateRequest,
    RunEventPageResponse,
    RunEventResponse,
    RunPageResponse,
    RunResponse,
    SemanticKnowledgeGraphResponse,
    SemanticRelationshipExpansionResponse,
    StagePageResponse,
    StageResponse,
)
from selene_service.domain.execution import ExecutionState, InvalidExecutionTransition
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
from selene_service.persistence.repositories import (
    ConcurrentReviewSubmissionError,
    ConcurrentRunTransitionError,
    NewRun,
    RunRepository,
)

_PAGE_MAXIMUM = 100
_RUN_CREATE_OPERATION = "runs.create"
_PRODUCT_CREATE_OPERATION = "products.create"
_RUN_CANCEL_OPERATION = "runs.cancel"
_RUN_REVIEW_OPERATION = "runs.review"
_KNOWLEDGE_ENTITY_CREATE_OPERATION = "knowledge.entities.create"
_KNOWLEDGE_EDGE_CREATE_OPERATION = "knowledge.edges.create"
_IDEMPOTENCY_RETENTION = timedelta(hours=24)
_RUN_CREATE_STATUS_CODE = 201
_SUCCESS_STATUS_CODE = 200
RecordT = TypeVar("RecordT")
ColumnT = TypeVar("ColumnT")
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


def _column_expression(column: InstrumentedAttribute[ColumnT]) -> ColumnElement[ColumnT]:
    """Expose an ORM class descriptor as the SQL expression used in a select.

    SQLAlchemy's runtime descriptor is both an instrumented attribute and a
    column expression.  The explicit boundary keeps the generic pagination
    helper strict without weakening type checking for its callers.
    """

    return cast(ColumnElement[ColumnT], column)


def list_products(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    validation_state: str | None,
    query: str | None,
) -> ProductPageResponse:
    """Return persisted product metadata with optional literal stored-field lookup."""

    statement = select(Product)
    if validation_state is not None:
        statement = statement.where(Product.validation_state == validation_state)
    if query is not None and query.strip():
        literal = _escaped_like_literal(query.strip().casefold())
        pattern = f"%{literal}%"
        statement = statement.where(
            or_(
                func.lower(Product.id.cast(String)).like(pattern, escape="\\"),
                func.lower(Product.product_identity).like(pattern, escape="\\"),
                func.lower(Product.payload_type).like(pattern, escape="\\"),
                func.lower(Product.manifest_sha256).like(pattern, escape="\\"),
            )
        )
    products, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(Product.created_at),
        _column_expression(Product.id),
        cursor,
        limit,
    )
    return ProductPageResponse(
        items=[_product_response(session, product) for product in products],
        next_cursor=next_cursor,
    )


def get_product(session: Session, product_id: UUID) -> ProductResponse:
    """Return one actual persisted product or a safe 404."""

    return _product_response(session, _require_product(session, product_id))


def create_product(
    session: Session,
    identity: SubjectIdentity,
    request: ProductCreateRequest,
    idempotency_key: str | None = None,
) -> ProductResponse:
    """Persist supplied product metadata and optional lunar geometry atomically."""

    with session.begin():
        subject = _resolve_subject(session, identity)
        request_digest = _command_request_digest(request)
        replayed = _replay_idempotent_response_if_present(
            session,
            subject.id,
            _PRODUCT_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            _RUN_CREATE_STATUS_CODE,
            ProductResponse,
        )
        if replayed is not None:
            return replayed
        footprint = _to_lunar_polygon(request.footprint_geojson)
        product = Product(
            owner_subject_id=subject.id,
            product_identity=request.product_identity,
            payload_type=request.payload_type,
            payload_metadata=cast(dict[str, object], request.payload_metadata),
            validation_state=request.validation_state,
            validation_details=cast(dict[str, object], request.validation_details),
            manifest_sha256=request.manifest_sha256,
            quarantine_reason=request.quarantine_reason,
            footprint=footprint,
            footprint_crs=request.footprint_crs,
            footprint_srid=request.footprint_srid,
        )
        session.add(product)
        session.flush()
        session.refresh(product)
        response = _product_response(session, product)
        _store_idempotent_response(
            session,
            subject.id,
            _PRODUCT_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            response,
            _RUN_CREATE_STATUS_CODE,
        )
    return response


def list_runs(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    execution_state: str | None,
    query: str | None,
) -> RunPageResponse:
    """Return persisted lifecycle state with optional literal stored-field lookup."""

    statement = select(Run)
    if execution_state is not None:
        statement = statement.where(Run.execution_state == execution_state)
    if query is not None and query.strip():
        literal = _escaped_like_literal(query.strip().casefold())
        pattern = f"%{literal}%"
        statement = statement.where(
            or_(
                func.lower(Run.id.cast(String)).like(pattern, escape="\\"),
                func.lower(Run.source_product_id.cast(String)).like(pattern, escape="\\"),
                func.lower(Run.reference_product_id.cast(String)).like(pattern, escape="\\"),
                func.lower(Run.code_revision).like(pattern, escape="\\"),
                func.lower(Run.environment_fingerprint).like(pattern, escape="\\"),
            )
        )
    runs, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(Run.created_at),
        _column_expression(Run.id),
        cursor,
        limit,
    )
    return RunPageResponse(
        items=[_run_response(run) for run in runs],
        next_cursor=next_cursor,
    )


def get_run(session: Session, run_id: UUID) -> RunResponse:
    """Return one persisted run without implying a worker has executed it."""

    return _run_response(_require_run(session, run_id))


def create_run(
    session: Session,
    identity: SubjectIdentity,
    request: RunCreateRequest,
    idempotency_key: str | None,
) -> RunResponse:
    """Record an immutable run definition and its creation event atomically."""

    canonical_manifest = _canonical_document(request.parameter_manifest)
    parameters_sha256 = _sha256(canonical_manifest)
    if request.parameters_sha256 is not None and request.parameters_sha256 != parameters_sha256:
        raise BadRequestProblem("parameters_sha256 does not match the canonical parameter manifest")
    parameter_document = cast(dict[str, object], json.loads(canonical_manifest))
    request_digest = _command_request_digest(request)

    with session.begin():
        subject = _resolve_subject(session, identity)
        if idempotency_key is not None:
            _validate_idempotency_key(idempotency_key)
            _acquire_idempotency_lock(session, subject.id, _RUN_CREATE_OPERATION, idempotency_key)
            existing_record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.subject_id == subject.id,
                    IdempotencyRecord.operation == _RUN_CREATE_OPERATION,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if existing_record is not None:
                return _replay_idempotent_response(
                    existing_record,
                    request_digest,
                    _RUN_CREATE_STATUS_CODE,
                    RunResponse,
                )

        _require_product(session, request.source_product_id)
        _require_product(session, request.reference_product_id)
        run = RunRepository().record_new_run(
            session,
            NewRun(
                owner_subject_id=subject.id,
                source_product_id=request.source_product_id,
                reference_product_id=request.reference_product_id,
                parameters_document=parameter_document,
                parameters_sha256=parameters_sha256,
                algorithm_versions=cast(dict[str, object], request.algorithm_versions),
                model_versions=cast(dict[str, object], request.model_versions),
                code_revision=request.code_revision,
                environment_fingerprint=request.environment_fingerprint,
            ),
        )
        session.flush()
        session.refresh(run)
        response = _run_response(run)
        if idempotency_key is not None:
            # Store the exact public creation document, not only the run ID.
            # Later lifecycle/review writes are intentionally mutable state,
            # whereas a same-key replay must remain the original response.
            session.add(
                IdempotencyRecord(
                    subject_id=subject.id,
                    operation=_RUN_CREATE_OPERATION,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    result_id=run.id,
                    response_document={
                        "body": cast(dict[str, object], response.model_dump(mode="json")),
                        "status_code": _RUN_CREATE_STATUS_CODE,
                    },
                    expires_at=datetime.now(UTC) + _IDEMPOTENCY_RETENTION,
                )
            )
    return response


def cancel_run(
    session: Session,
    identity: SubjectIdentity,
    run_id: UUID,
    idempotency_key: str | None = None,
) -> RunResponse:
    """Record the only permitted cancellation transition for the current state."""

    with session.begin():
        subject = _resolve_subject(session, identity)
        request_digest = _command_request_digest({"run_id": str(run_id)})
        replayed = _replay_idempotent_response_if_present(
            session,
            subject.id,
            _RUN_CANCEL_OPERATION,
            idempotency_key,
            request_digest,
            _SUCCESS_STATUS_CODE,
            RunResponse,
        )
        if replayed is not None:
            return replayed
        run = _require_run(session, run_id)
        target = _cancellation_target(run.execution_state)
        try:
            RunRepository().transition_execution_state(
                session,
                run,
                target,
                actor_subject_id=subject.id,
                event_document={"request_kind": "cancellation"},
            )
        except (ConcurrentRunTransitionError, InvalidExecutionTransition) as exception:
            raise ConflictProblem() from exception
        session.flush()
        session.refresh(run)
        response = _run_response(run)
        _store_idempotent_response(
            session,
            subject.id,
            _RUN_CANCEL_OPERATION,
            idempotency_key,
            request_digest,
            response,
            _SUCCESS_STATUS_CODE,
        )
    return response


def list_stages(
    session: Session,
    run_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> StagePageResponse:
    """List only stage records written by a trusted runner."""

    _require_run(session, run_id)
    stages, next_cursor = _cursor_page(
        session,
        select(RunStage).where(RunStage.run_id == run_id),
        _column_expression(RunStage.created_at),
        _column_expression(RunStage.id),
        cursor,
        limit,
    )
    return StagePageResponse(
        items=[_stage_response(stage) for stage in stages],
        next_cursor=next_cursor,
    )


def list_artifacts(
    session: Session,
    run_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> ArtifactPageResponse:
    """List only already-published artifact records for a persisted run."""

    _require_run(session, run_id)
    artifacts, next_cursor = _cursor_page(
        session,
        select(Artifact).where(Artifact.run_id == run_id),
        _column_expression(Artifact.created_at),
        _column_expression(Artifact.id),
        cursor,
        limit,
    )
    return ArtifactPageResponse(
        items=[_artifact_response(artifact) for artifact in artifacts],
        next_cursor=next_cursor,
    )


def list_metrics(
    session: Session,
    run_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> MetricPageResponse:
    """List only persisted metric reports; an empty page means none were stored."""

    _require_run(session, run_id)
    metrics, next_cursor = _cursor_page(
        session,
        select(Metric).where(Metric.run_id == run_id),
        _column_expression(Metric.created_at),
        _column_expression(Metric.id),
        cursor,
        limit,
    )
    return MetricPageResponse(
        items=[_metric_response(metric) for metric in metrics],
        next_cursor=next_cursor,
    )


def list_events(
    session: Session,
    run_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> RunEventPageResponse:
    """List the real append-only run event history."""

    _require_run(session, run_id)
    events, next_cursor = _cursor_page(
        session,
        select(RunEvent).where(RunEvent.run_id == run_id),
        _column_expression(RunEvent.recorded_at),
        _column_expression(RunEvent.id),
        cursor,
        limit,
    )
    return RunEventPageResponse(
        items=[_event_response(event) for event in events],
        next_cursor=next_cursor,
    )


def submit_review(
    session: Session,
    identity: SubjectIdentity,
    run_id: UUID,
    request: ReviewCreateRequest,
    idempotency_key: str | None = None,
) -> ReviewResponse:
    """Append an immutable review plus matching durable run provenance event."""

    with session.begin():
        if identity.role is not None and identity.role not in ("reviewer", "admin"):
            raise APIProblem(403, "forbidden", "The request is not permitted.")
        subject = _resolve_subject(session, identity)
        request_digest = _command_request_digest(
            {"run_id": str(run_id), **request.model_dump(mode="json", exclude_none=True)}
        )
        replayed = _replay_idempotent_response_if_present(
            session,
            subject.id,
            _RUN_REVIEW_OPERATION,
            idempotency_key,
            request_digest,
            _RUN_CREATE_STATUS_CODE,
            ReviewResponse,
        )
        if replayed is not None:
            return replayed
        run = _require_run(session, run_id)
        if run.execution_state != ExecutionState.SUCCEEDED.value or run.computed_verdict is None:
            raise ConflictProblem(
                "A review requires a succeeded run with a persisted computed verdict."
            )
        try:
            review = RunRepository().record_review(
                session,
                run,
                actor_subject_id=subject.id,
                decision=request.decision,
                reason_code=request.reason_code,
                note=request.note,
            )
        except ConcurrentReviewSubmissionError as exception:
            raise ConflictProblem() from exception
        session.flush()
        session.refresh(review)
        response = _review_response(review)
        _store_idempotent_response(
            session,
            subject.id,
            _RUN_REVIEW_OPERATION,
            idempotency_key,
            request_digest,
            response,
            _RUN_CREATE_STATUS_CODE,
        )
    return response


def list_reviews(
    session: Session,
    run_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> ReviewPageResponse:
    """Return immutable persisted review history in pages."""

    _require_run(session, run_id)
    reviews, next_cursor = _cursor_page(
        session,
        select(Review).where(Review.run_id == run_id),
        _column_expression(Review.recorded_at),
        _column_expression(Review.id),
        cursor,
        limit,
    )
    return ReviewPageResponse(
        items=[_review_response(review) for review in reviews],
        next_cursor=next_cursor,
    )


def list_knowledge_entities(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    entity_type: str | None,
    external_id: str | None,
) -> KnowledgeEntityPageResponse:
    """Browse explicitly persisted semantic entities, never seeded fixtures."""

    statement = select(KnowledgeEntity)
    if entity_type is not None:
        statement = statement.where(KnowledgeEntity.entity_type == entity_type)
    if external_id is not None:
        statement = statement.where(KnowledgeEntity.external_id == external_id)
    entities, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(KnowledgeEntity.created_at),
        _column_expression(KnowledgeEntity.id),
        cursor,
        limit,
    )
    return KnowledgeEntityPageResponse(
        items=[_knowledge_entity_response(session, entity) for entity in entities],
        next_cursor=next_cursor,
    )


def get_knowledge_entity(session: Session, entity_id: UUID) -> KnowledgeEntityResponse:
    """Fetch one persisted semantic entity."""

    return _knowledge_entity_response(session, _require_knowledge_entity(session, entity_id))


def create_knowledge_entity(
    session: Session,
    identity: SubjectIdentity,
    request: KnowledgeEntityCreateRequest,
    idempotency_key: str | None = None,
) -> KnowledgeEntityResponse:
    """Persist an explicit generic semantic entity transactionally."""

    with session.begin():
        subject = _resolve_subject(session, identity)
        request_digest = _command_request_digest(request)
        replayed = _replay_idempotent_response_if_present(
            session,
            subject.id,
            _KNOWLEDGE_ENTITY_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            _RUN_CREATE_STATUS_CODE,
            KnowledgeEntityResponse,
        )
        if replayed is not None:
            return replayed
        entity = KnowledgeEntity(
            created_by_subject_id=subject.id,
            entity_type=request.entity_type,
            external_id=request.external_id,
            label=request.label,
            properties=cast(dict[str, object], request.properties),
            location=_to_lunar_point(request.location_geojson),
            location_crs=request.location_crs,
            location_srid=request.location_srid,
        )
        session.add(entity)
        session.flush()
        session.refresh(entity)
        response = _knowledge_entity_response(session, entity)
        _store_idempotent_response(
            session,
            subject.id,
            _KNOWLEDGE_ENTITY_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            response,
            _RUN_CREATE_STATUS_CODE,
        )
    return response


def list_knowledge_edges(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    source_entity_id: UUID | None,
    target_entity_id: UUID | None,
    relation_type: str | None,
) -> KnowledgeEdgePageResponse:
    """Browse only stored semantic relationships."""

    statement = select(KnowledgeEdge)
    if source_entity_id is not None:
        statement = statement.where(KnowledgeEdge.source_entity_id == source_entity_id)
    if target_entity_id is not None:
        statement = statement.where(KnowledgeEdge.target_entity_id == target_entity_id)
    if relation_type is not None:
        statement = statement.where(KnowledgeEdge.relation_type == relation_type)
    edges, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(KnowledgeEdge.created_at),
        _column_expression(KnowledgeEdge.id),
        cursor,
        limit,
    )
    return KnowledgeEdgePageResponse(
        items=[_knowledge_edge_response(edge) for edge in edges],
        next_cursor=next_cursor,
    )


def create_knowledge_edge(
    session: Session,
    identity: SubjectIdentity,
    request: KnowledgeEdgeCreateRequest,
    idempotency_key: str | None = None,
) -> KnowledgeEdgeResponse:
    """Persist a relationship only after both semantic endpoints are present."""

    with session.begin():
        subject = _resolve_subject(session, identity)
        request_digest = _command_request_digest(request)
        replayed = _replay_idempotent_response_if_present(
            session,
            subject.id,
            _KNOWLEDGE_EDGE_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            _RUN_CREATE_STATUS_CODE,
            KnowledgeEdgeResponse,
        )
        if replayed is not None:
            return replayed
        _require_knowledge_entity(session, request.source_entity_id)
        _require_knowledge_entity(session, request.target_entity_id)
        edge = KnowledgeEdge(
            created_by_subject_id=subject.id,
            source_entity_id=request.source_entity_id,
            target_entity_id=request.target_entity_id,
            relation_type=request.relation_type,
            properties=cast(dict[str, object], request.properties),
            weight=request.weight,
        )
        session.add(edge)
        session.flush()
        session.refresh(edge)
        response = _knowledge_edge_response(edge)
        _store_idempotent_response(
            session,
            subject.id,
            _KNOWLEDGE_EDGE_CREATE_OPERATION,
            idempotency_key,
            request_digest,
            response,
            _RUN_CREATE_STATUS_CODE,
        )
    return response


def knowledge_neighbors(
    session: Session,
    entity_id: UUID,
    *,
    cursor: str | None,
    limit: int,
    relation_type: str | None,
    neighbor_entity_type: str | None = None,
) -> SemanticKnowledgeGraphResponse:
    """Return direct durable neighbors and their stored relation rows."""

    center = _require_knowledge_entity(session, entity_id)
    statement = select(KnowledgeEdge).where(
        or_(
            KnowledgeEdge.source_entity_id == entity_id,
            KnowledgeEdge.target_entity_id == entity_id,
        )
    )
    if relation_type is not None:
        statement = statement.where(KnowledgeEdge.relation_type == relation_type)
    edges, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(KnowledgeEdge.created_at),
        _column_expression(KnowledgeEdge.id),
        cursor,
        limit,
    )
    neighbor_ids = {
        edge.target_entity_id if edge.source_entity_id == entity_id else edge.source_entity_id
        for edge in edges
    }
    neighbors = _knowledge_entities_by_id(session, neighbor_ids)
    if neighbor_entity_type is not None:
        neighbors = [entity for entity in neighbors if entity.entity_type == neighbor_entity_type]
        accepted_neighbor_ids = {entity.id for entity in neighbors}
        edges = [
            edge
            for edge in edges
            if (
                edge.target_entity_id
                if edge.source_entity_id == entity_id
                else edge.source_entity_id
            )
            in accepted_neighbor_ids
        ]
    return SemanticKnowledgeGraphResponse(
        nodes=[_knowledge_entity_response(session, entity) for entity in [center, *neighbors]],
        edges=[_knowledge_edge_response(edge) for edge in edges],
        next_cursor=next_cursor,
    )


def query_knowledge(
    session: Session,
    *,
    query: str | None,
    entity_type: str | None,
    relation_type: str | None,
    cursor: str | None,
    limit: int,
) -> SemanticKnowledgeGraphResponse:
    """Run deterministic lexical and exact filters over persisted semantic rows.

    This deliberately has no embedding, similarity score, ranking model, or
    natural-language inference.  A text query is a case-insensitive literal
    substring match over labels and external IDs; relation filtering is exact.
    """

    statement = select(KnowledgeEntity)
    if entity_type is not None:
        statement = statement.where(KnowledgeEntity.entity_type == entity_type)
    if query is not None and query.strip():
        literal = _escaped_like_literal(query.strip().casefold())
        pattern = f"%{literal}%"
        statement = statement.where(
            or_(
                func.lower(KnowledgeEntity.label).like(pattern, escape="\\"),
                func.lower(KnowledgeEntity.external_id).like(pattern, escape="\\"),
            )
        )
    if relation_type is not None:
        # Apply the relationship filter to entity selection itself.  Returning
        # a CRATER merely because it matches a label while it has no matching
        # edge would make a relation-filtered result misleading.
        statement = statement.where(
            select(KnowledgeEdge.id)
            .where(
                KnowledgeEdge.relation_type == relation_type,
                or_(
                    KnowledgeEdge.source_entity_id == KnowledgeEntity.id,
                    KnowledgeEdge.target_entity_id == KnowledgeEntity.id,
                ),
            )
            .exists()
        )
    entities, next_cursor = _cursor_page(
        session,
        statement,
        _column_expression(KnowledgeEntity.created_at),
        _column_expression(KnowledgeEntity.id),
        cursor,
        limit,
    )
    entity_ids = {entity.id for entity in entities}
    edges: list[KnowledgeEdge] = []
    overflow_edge: KnowledgeEdge | None = None
    output_entity_ids = set(entity_ids)
    if entity_ids:
        if relation_type is not None:
            edge_statement = select(KnowledgeEdge).where(
                KnowledgeEdge.relation_type == relation_type,
                or_(
                    KnowledgeEdge.source_entity_id.in_(entity_ids),
                    KnowledgeEdge.target_entity_id.in_(entity_ids),
                ),
            )
        else:
            edge_statement = select(KnowledgeEdge).where(
                KnowledgeEdge.source_entity_id.in_(entity_ids),
                KnowledgeEdge.target_entity_id.in_(entity_ids),
            )
        # The cursor belongs to the root entity page. Fetch one overflow edge
        # so a bounded relationship expansion can never be represented as a
        # complete graph. Per-root neighbour routes expose their own cursors.
        page_limit = _validate_page_limit(limit)
        edge_statement = edge_statement.order_by(
            KnowledgeEdge.created_at.desc(), KnowledgeEdge.id.desc()
        ).limit(page_limit + 1)
        candidate_edges = list(session.scalars(edge_statement).all())
        edges = candidate_edges[:page_limit]
        overflow_edge = candidate_edges[page_limit] if len(candidate_edges) > page_limit else None
        output_entity_ids.update(
            endpoint_id
            for edge in edges
            for endpoint_id in (edge.source_entity_id, edge.target_entity_id)
        )
    output_entities = _knowledge_entities_by_id(session, output_entity_ids)
    expansion_root_ids = (
        # The capped edge query is ordered globally across this root page.
        # Once it overflows, any selected root could have omitted older edges,
        # so expose a paginatable continuation for every root—not just the
        # root incident to the one observed overflow row.
        sorted(entity_ids, key=str)
        if overflow_edge is not None
        else []
    )
    return SemanticKnowledgeGraphResponse(
        nodes=[_knowledge_entity_response(session, entity) for entity in output_entities],
        edges=[_knowledge_edge_response(edge) for edge in edges],
        next_cursor=next_cursor,
        edges_truncated=overflow_edge is not None,
        relationship_expansions=[
            SemanticRelationshipExpansionResponse(
                entity_id=entity_id,
                neighbors_path=f"/api/v1/knowledge/entities/{entity_id}/neighbors",
            )
            for entity_id in expansion_root_ids
        ],
    )


def crater_detail(session: Session, entity_id: UUID) -> KnowledgeEntityResponse:
    """Return a crater-compatible detail only for a stored CRATER entity."""

    entity = _require_knowledge_entity(session, entity_id)
    if entity.entity_type != "CRATER":
        raise NotFoundProblem()
    return _knowledge_entity_response(session, entity)


def crater_observations(
    session: Session,
    crater_id: UUID,
    *,
    cursor: str | None,
    limit: int,
) -> SemanticKnowledgeGraphResponse:
    """Return only persisted OBSERVATION neighbors linked to a stored crater."""

    entity = _require_knowledge_entity(session, crater_id)
    if entity.entity_type != "CRATER":
        raise NotFoundProblem()
    return knowledge_neighbors(
        session,
        crater_id,
        cursor=cursor,
        limit=limit,
        relation_type="OBSERVED_IN",
        neighbor_entity_type="OBSERVATION",
    )


def knowledge_graph(
    session: Session,
    *,
    center_type: str | None,
    center_id: UUID | None,
    cursor: str | None,
    limit: int,
) -> KnowledgeGraphResponse:
    """Project DB foreign keys into a stable, fixture-free provenance graph."""

    if (center_type is None) != (center_id is None):
        raise BadRequestProblem("center_type and center_id must be supplied together")
    if center_type not in {None, "run", "product"}:
        raise BadRequestProblem("center_type must be either run or product")

    next_cursor: str | None = None
    products: dict[UUID, Product] = {}
    if center_type == "run":
        if center_id is None:
            raise BadRequestProblem("center_id is required for a run graph")
        runs = [_require_run(session, center_id)]
    elif center_type == "product":
        if center_id is None:
            raise BadRequestProblem("center_id is required for a product graph")
        center_product = _require_product(session, center_id)
        products[center_product.id] = center_product
        runs, next_cursor = _cursor_page(
            session,
            select(Run).where(
                or_(Run.source_product_id == center_id, Run.reference_product_id == center_id)
            ),
            _column_expression(Run.created_at),
            _column_expression(Run.id),
            cursor,
            limit,
        )
    else:
        runs, next_cursor = _cursor_page(
            session,
            select(Run),
            _column_expression(Run.created_at),
            _column_expression(Run.id),
            cursor,
            limit,
        )

    run_ids = [run.id for run in runs]
    product_ids = {
        product_id
        for run in runs
        for product_id in (run.source_product_id, run.reference_product_id)
    }
    if product_ids:
        products.update(
            {
                product.id: product
                for product in session.scalars(
                    select(Product).where(Product.id.in_(product_ids))
                ).all()
            }
        )

    # Each child collection has an explicit independent upper bound.  The
    # graph cursor is for root runs only, so this projection intentionally
    # reports a recent bounded slice rather than silently loading all history.
    stages, stages_truncated = _records_for_run_ids(
        session,
        select(RunStage),
        _column_expression(RunStage.run_id),
        _column_expression(RunStage.created_at),
        _column_expression(RunStage.id),
        run_ids,
        limit,
    )
    artifacts, artifacts_truncated = _records_for_run_ids(
        session,
        select(Artifact),
        _column_expression(Artifact.run_id),
        _column_expression(Artifact.created_at),
        _column_expression(Artifact.id),
        run_ids,
        limit,
    )
    metrics, metrics_truncated = _records_for_run_ids(
        session,
        select(Metric),
        _column_expression(Metric.run_id),
        _column_expression(Metric.created_at),
        _column_expression(Metric.id),
        run_ids,
        limit,
    )
    reviews, reviews_truncated = _records_for_run_ids(
        session,
        select(Review),
        _column_expression(Review.run_id),
        _column_expression(Review.recorded_at),
        _column_expression(Review.id),
        run_ids,
        limit,
    )
    subject_ids = {
        *[product.owner_subject_id for product in products.values()],
        *[run.owner_subject_id for run in runs],
        *[review.actor_subject_id for review in reviews],
    }
    subjects = {
        subject.id: subject
        for subject in session.scalars(select(Subject).where(Subject.id.in_(subject_ids))).all()
    } if subject_ids else {}

    nodes: dict[str, GraphNodeResponse] = {}
    edges: dict[str, GraphEdgeResponse] = {}

    for subject in subjects.values():
        _add_node(nodes, _subject_node(subject))
    for product in products.values():
        _add_node(nodes, _product_node(product))
        _add_edge(
            edges,
            _edge(
                _product_node_id(product.id),
                _subject_node_id(product.owner_subject_id),
                "owned_by",
            ),
        )
    for run in runs:
        _add_node(nodes, _run_node(run))
        _add_edge(
            edges,
            _edge(_run_node_id(run.id), _subject_node_id(run.owner_subject_id), "owned_by"),
        )
        _add_edge(
            edges,
            _edge(_run_node_id(run.id), _product_node_id(run.source_product_id), "uses_source"),
        )
        _add_edge(
            edges,
            _edge(
                _run_node_id(run.id),
                _product_node_id(run.reference_product_id),
                "uses_reference",
            ),
        )
    for stage in stages:
        _add_node(nodes, _stage_node(stage))
        _add_edge(edges, _edge(_stage_node_id(stage.id), _run_node_id(stage.run_id), "part_of"))
    stage_ids = {stage.id for stage in stages}
    for artifact in artifacts:
        _add_node(nodes, _artifact_node(artifact))
        _add_edge(
            edges,
            _edge(_artifact_node_id(artifact.id), _run_node_id(artifact.run_id), "artifact_of"),
        )
        if artifact.run_stage_id is not None and artifact.run_stage_id in stage_ids:
            _add_edge(
                edges,
                _edge(
                    _artifact_node_id(artifact.id),
                    _stage_node_id(artifact.run_stage_id),
                    "produced_by",
                ),
            )
    for metric in metrics:
        _add_node(nodes, _metric_node(metric))
        _add_edge(
            edges,
            _edge(_metric_node_id(metric.id), _run_node_id(metric.run_id), "reported_for"),
        )
    for review in reviews:
        _add_node(nodes, _review_node(review))
        _add_edge(edges, _edge(_review_node_id(review.id), _run_node_id(review.run_id), "reviews"))
        _add_edge(
            edges,
            _edge(
                _review_node_id(review.id),
                _subject_node_id(review.actor_subject_id),
                "submitted_by",
            ),
        )

    truncated_collections: tuple[
        tuple[Literal["stages", "artifacts", "metrics", "reviews"], bool], ...
    ] = (
        ("stages", stages_truncated),
        ("artifacts", artifacts_truncated),
        ("metrics", metrics_truncated),
        ("reviews", reviews_truncated),
    )
    return KnowledgeGraphResponse(
        nodes=sorted(nodes.values(), key=lambda node: node.id),
        edges=sorted(edges.values(), key=lambda edge: edge.id),
        next_cursor=next_cursor,
        child_collections_truncated=[
            GraphCollectionTruncationResponse(collection=collection, limit=limit)
            for collection, is_truncated in truncated_collections
            if is_truncated
        ],
    )


def _require_product(session: Session, product_id: UUID) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundProblem()
    return product


def _require_run(session: Session, run_id: UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise NotFoundProblem()
    return run


def _require_knowledge_entity(session: Session, entity_id: UUID) -> KnowledgeEntity:
    entity = session.get(KnowledgeEntity, entity_id)
    if entity is None:
        raise NotFoundProblem()
    return entity


def _knowledge_entities_by_id(session: Session, entity_ids: set[UUID]) -> list[KnowledgeEntity]:
    if not entity_ids:
        return []
    return list(
        session.scalars(
            select(KnowledgeEntity)
            .where(KnowledgeEntity.id.in_(entity_ids))
            .order_by(KnowledgeEntity.created_at.desc(), KnowledgeEntity.id.desc())
        ).all()
    )


def _resolve_subject(session: Session, identity: SubjectIdentity) -> Subject:
    """Create or fetch a subject without a first-request unique-key race."""

    session.execute(
        postgresql_insert(Subject)
        .values(
            subject_name=identity.subject_name,
            subject_type=identity.subject_type,
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=[Subject.subject_name])
    )
    subject = session.scalar(select(Subject).where(Subject.subject_name == identity.subject_name))
    if subject is None:
        raise RuntimeError("Subject upsert completed without a readable subject row")
    if not subject.is_active:
        raise ConflictProblem("The current subject is inactive.")
    return subject


def _validate_idempotency_key(idempotency_key: str) -> None:
    if not idempotency_key.strip() or len(idempotency_key) > 255:
        raise BadRequestProblem("Idempotency-Key must contain between 1 and 255 characters")


def _acquire_idempotency_lock(
    session: Session,
    subject_id: UUID,
    operation: str,
    idempotency_key: str,
) -> None:
    """Serialise same-key creation attempts before checking the unique record."""

    lock_material = f"{subject_id}:{operation}:{idempotency_key}"
    lock_digest = hashlib.sha256(lock_material.encode()).digest()
    lock_key = int.from_bytes(lock_digest[:8], byteorder="big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(lock_key)))


def _replay_idempotent_response_if_present(
    session: Session,
    subject_id: UUID,
    operation: str,
    idempotency_key: str | None,
    request_digest: str,
    status_code: int,
    response_model: type[ResponseModelT],
) -> ResponseModelT | None:
    """Return a frozen response after serialising a same-key command retry."""

    if idempotency_key is None:
        return None
    _validate_idempotency_key(idempotency_key)
    _acquire_idempotency_lock(session, subject_id, operation, idempotency_key)
    existing_record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.subject_id == subject_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing_record is None:
        return None
    return _replay_idempotent_response(
        existing_record,
        request_digest,
        status_code,
        response_model,
    )


def _store_idempotent_response(
    session: Session,
    subject_id: UUID,
    operation: str,
    idempotency_key: str | None,
    request_digest: str,
    response: BaseModel,
    status_code: int,
) -> None:
    """Persist an exact public result once, in the caller's transaction."""

    if idempotency_key is None:
        return
    result_id = getattr(response, "id", None)
    session.add(
        IdempotencyRecord(
            subject_id=subject_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result_id=result_id if isinstance(result_id, UUID) else None,
            response_document={
                "body": cast(dict[str, object], response.model_dump(mode="json")),
                "status_code": status_code,
            },
            expires_at=datetime.now(UTC) + _IDEMPOTENCY_RETENTION,
        )
    )


def _replay_idempotent_response(
    record: IdempotencyRecord,
    request_digest: str,
    status_code: int,
    response_model: type[ResponseModelT],
) -> ResponseModelT:
    if record.request_digest != request_digest:
        raise ConflictProblem("Idempotency-Key has already been used with a different request")
    if record.expires_at < datetime.now(UTC):
        raise ConflictProblem("Idempotency-Key has expired and cannot be replayed")
    document = record.response_document
    if not isinstance(document, dict) or document.get("status_code") != status_code:
        raise ConflictProblem("The stored idempotency response is unavailable")
    body = document.get("body")
    if not isinstance(body, dict):
        raise ConflictProblem()
    try:
        return response_model.model_validate(body)
    except (TypeError, ValueError) as exception:
        raise ConflictProblem("The stored idempotency response is unavailable") from exception


def _cancellation_target(current_state: str) -> ExecutionState:
    state = ExecutionState(current_state)
    if state in {ExecutionState.CREATED, ExecutionState.QUEUED}:
        return ExecutionState.CANCELLED
    if state is ExecutionState.RUNNING:
        return ExecutionState.CANCELLING
    raise ConflictProblem("The run cannot be cancelled from its current execution state.")


def _canonical_document(document: dict[str, JsonValue]) -> str:
    try:
        return json.dumps(document, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exception:
        raise BadRequestProblem("Parameter manifest must be canonical JSON data") from exception


def _command_request_digest(request: BaseModel | dict[str, object]) -> str:
    """Canonicalise a public command document before idempotency comparison."""

    if isinstance(request, BaseModel):
        document = request.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        document = request
    return _sha256(_canonical_document(cast(dict[str, JsonValue], document)))


def _sha256(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def _cursor_page(
    session: Session,
    statement: Select[tuple[RecordT]],
    timestamp_column: ColumnElement[datetime],
    identifier_column: ColumnElement[UUID],
    cursor: str | None,
    limit: int,
) -> tuple[list[RecordT], str | None]:
    """Apply stable newest-first UUID/timestamp cursor pagination."""

    page_size = _validate_page_limit(limit)
    cursor_value = _decode_cursor(cursor) if cursor is not None else None
    if cursor_value is not None:
        statement = statement.where(
            or_(
                timestamp_column < cursor_value[0],
                and_(timestamp_column == cursor_value[0], identifier_column < cursor_value[1]),
            )
        )
    statement = statement.order_by(
        timestamp_column.desc(),
        identifier_column.desc(),
    ).limit(page_size + 1)
    records = list(session.scalars(statement).all())
    if len(records) <= page_size:
        return records, None
    # Retain the overflow row for the following request.  The cursor must
    # identify the final *returned* record; using the removed overflow record
    # would exclude it from the next SQL predicate and silently omit it.
    records = records[:page_size]
    last_returned_record = records[-1]
    next_timestamp = getattr(last_returned_record, "created_at", None)
    if next_timestamp is None:
        next_timestamp = getattr(last_returned_record, "recorded_at", None)
    if not isinstance(next_timestamp, datetime):
        raise RuntimeError("Persisted record lacks a cursor timestamp")
    next_id = getattr(last_returned_record, "id", None)
    if not isinstance(next_id, UUID):
        raise RuntimeError("Persisted record lacks a UUID cursor identifier")
    return records, _encode_cursor(next_timestamp, next_id)


def _validate_page_limit(limit: int) -> int:
    if not 1 <= limit <= _PAGE_MAXIMUM:
        raise BadRequestProblem(f"limit must be between 1 and {_PAGE_MAXIMUM}")
    return limit


def _encode_cursor(timestamp: datetime, record_id: UUID) -> str:
    document = json.dumps(
        {"created_at": timestamp.astimezone(UTC).isoformat(), "id": str(record_id)},
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(document.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        document = json.loads(base64.urlsafe_b64decode(cursor + padding))
        timestamp = datetime.fromisoformat(document["created_at"])
        record_id = UUID(document["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exception:
        raise BadRequestProblem("cursor is invalid") from exception
    if timestamp.tzinfo is None:
        raise BadRequestProblem("cursor is invalid")
    return timestamp, record_id


def _to_lunar_polygon(geometry: dict[str, JsonValue] | None) -> WKBElement | None:
    if geometry is None:
        return None
    if geometry.get("type") != "Polygon":
        raise BadRequestProblem("footprint_geojson must be a GeoJSON Polygon")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise BadRequestProblem("footprint_geojson requires one or more linear rings")
    rings: list[str] = []
    for ring in coordinates:
        if not isinstance(ring, list) or len(ring) < 4:
            raise BadRequestProblem("each footprint ring must contain at least four positions")
        positions: list[tuple[float, float]] = []
        for position in ring:
            if (
                not isinstance(position, list)
                or len(position) < 2
                or isinstance(position[0], bool)
                or isinstance(position[1], bool)
                or not isinstance(position[0], (int, float))
                or not isinstance(position[1], (int, float))
            ):
                raise BadRequestProblem(
                    "footprint coordinates must be finite numeric longitude/latitude pairs"
                )
            longitude, latitude = float(position[0]), float(position[1])
            if not math.isfinite(longitude) or not math.isfinite(latitude):
                raise BadRequestProblem("footprint coordinates must be finite")
            positions.append((longitude, latitude))
        if positions[0] != positions[-1]:
            raise BadRequestProblem("each footprint ring must be closed")
        coordinate_text = ",".join(
            f"{longitude:.17g} {latitude:.17g}" for longitude, latitude in positions
        )
        rings.append(coordinate_text)
    # The Geometry column deliberately has SRID -1.  The actual lunar CRS is
    # stored separately in footprint_crs, never silently coerced to Earth.
    polygon_wkt = f"POLYGON({','.join(f'({ring})' for ring in rings)})"
    return cast(WKBElement, WKTElement(polygon_wkt, srid=-1))


def _to_lunar_point(geometry: dict[str, JsonValue] | None) -> WKBElement | None:
    if geometry is None:
        return None
    if geometry.get("type") != "Point":
        raise BadRequestProblem("location_geojson must be a GeoJSON Point")
    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) < 2
        or isinstance(coordinates[0], bool)
        or isinstance(coordinates[1], bool)
        or not isinstance(coordinates[0], (int, float))
        or not isinstance(coordinates[1], (int, float))
    ):
        raise BadRequestProblem("location coordinates must be a finite longitude/latitude pair")
    longitude, latitude = float(coordinates[0]), float(coordinates[1])
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise BadRequestProblem("location coordinates must be finite")
    return cast(WKBElement, WKTElement(f"POINT({longitude:.17g} {latitude:.17g})", srid=-1))


def _product_response(session: Session, product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        owner_subject_id=product.owner_subject_id,
        product_identity=product.product_identity,
        payload_type=product.payload_type,
        payload_metadata=cast(dict[str, JsonValue], product.payload_metadata),
        validation_state=product.validation_state,
        validation_details=cast(dict[str, JsonValue], product.validation_details),
        manifest_sha256=product.manifest_sha256,
        quarantine_reason=product.quarantine_reason,
        footprint_geojson=_stored_footprint_geojson(session, product),
        footprint_crs=product.footprint_crs,
        footprint_srid=product.footprint_srid,
        created_at=product.created_at,
    )


def _stored_footprint_geojson(session: Session, product: Product) -> dict[str, JsonValue] | None:
    if product.footprint is None:
        return None
    raw_geojson = session.scalar(
        select(func.ST_AsGeoJSON(Product.footprint)).where(Product.id == product.id)
    )
    if raw_geojson is None:
        return None
    try:
        geometry = json.loads(cast(str, raw_geojson))
    except (TypeError, json.JSONDecodeError) as exception:
        raise RuntimeError("Persisted footprint is not valid GeoJSON") from exception
    if not isinstance(geometry, dict):
        raise RuntimeError("Persisted footprint is not a GeoJSON object")
    return cast(dict[str, JsonValue], geometry)


def _run_response(run: Run) -> RunResponse:
    parameter_manifest = (
        None
        if run.parameters_document is None
        else cast(dict[str, JsonValue], run.parameters_document)
    )
    return RunResponse(
        id=run.id,
        owner_subject_id=run.owner_subject_id,
        source_product_id=run.source_product_id,
        reference_product_id=run.reference_product_id,
        parameter_manifest=parameter_manifest,
        parameter_manifest_available=parameter_manifest is not None,
        parameters_sha256=run.parameters_sha256,
        algorithm_versions=cast(dict[str, JsonValue], run.algorithm_versions),
        model_versions=cast(dict[str, JsonValue], run.model_versions),
        execution_state=run.execution_state,
        state_version=run.state_version,
        event_sequence=run.event_sequence,
        computed_verdict=run.computed_verdict,
        effective_disposition=run.effective_disposition,
        code_revision=run.code_revision,
        environment_fingerprint=run.environment_fingerprint,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _stage_response(stage: RunStage) -> StageResponse:
    return StageResponse(
        id=stage.id,
        run_id=stage.run_id,
        stage_name=stage.stage_name,
        stage_ordinal=stage.stage_ordinal,
        attempt=stage.attempt,
        execution_state=stage.execution_state,
        input_sha256=stage.input_sha256,
        output_sha256=stage.output_sha256,
        lease_holder=stage.lease_holder,
        lease_expires_at=stage.lease_expires_at,
        warning_document=cast(dict[str, JsonValue] | None, stage.warning_document),
        failure_document=cast(dict[str, JsonValue] | None, stage.failure_document),
        completed_at=stage.completed_at,
        atomic_completion_marker=stage.atomic_completion_marker,
        created_at=stage.created_at,
    )


def _artifact_response(artifact: Artifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        run_id=artifact.run_id,
        run_stage_id=artifact.run_stage_id,
        kind=artifact.kind,
        storage_uri=artifact.storage_uri,
        media_type=artifact.media_type,
        byte_size=artifact.byte_size,
        sha256=artifact.sha256,
        schema_uri=artifact.schema_uri,
        crs_metadata=cast(dict[str, JsonValue] | None, artifact.crs_metadata),
        validation_document=cast(dict[str, JsonValue], artifact.validation_document),
        publication_state=artifact.publication_state,
        validated_at=artifact.validated_at,
        published_at=artifact.published_at,
        created_at=artifact.created_at,
    )


def _metric_response(metric: Metric) -> MetricResponse:
    return MetricResponse(
        id=metric.id,
        run_id=metric.run_id,
        report_kind=metric.report_kind,
        report_version=metric.report_version,
        report_document=cast(dict[str, JsonValue], metric.report_document),
        indexed_fields=cast(dict[str, JsonValue], metric.indexed_fields),
        computed_verdict=metric.computed_verdict,
        created_at=metric.created_at,
    )


def _event_response(event: RunEvent) -> RunEventResponse:
    return RunEventResponse(
        id=event.id,
        run_id=event.run_id,
        actor_subject_id=event.actor_subject_id,
        event_type=event.event_type,
        execution_state=event.execution_state,
        sequence=event.sequence,
        event_document=cast(dict[str, JsonValue], event.event_document),
        recorded_at=event.recorded_at,
    )


def _review_response(review: Review) -> ReviewResponse:
    return ReviewResponse(
        id=review.id,
        run_id=review.run_id,
        actor_subject_id=review.actor_subject_id,
        decision=review.decision,
        reason_code=review.reason_code,
        note=review.note,
        source_computed_verdict=review.source_computed_verdict,
        recorded_at=review.recorded_at,
    )


def _knowledge_entity_response(
    session: Session,
    entity: KnowledgeEntity,
) -> KnowledgeEntityResponse:
    return KnowledgeEntityResponse(
        id=entity.id,
        created_by_subject_id=entity.created_by_subject_id,
        entity_type=entity.entity_type,
        external_id=entity.external_id,
        label=entity.label,
        properties=cast(dict[str, JsonValue], entity.properties),
        location_geojson=_stored_knowledge_location_geojson(session, entity),
        location_crs=entity.location_crs,
        location_srid=entity.location_srid,
        created_at=entity.created_at,
    )


def _stored_knowledge_location_geojson(
    session: Session,
    entity: KnowledgeEntity,
) -> dict[str, JsonValue] | None:
    if entity.location is None:
        return None
    raw_geojson = session.scalar(
        select(func.ST_AsGeoJSON(KnowledgeEntity.location)).where(KnowledgeEntity.id == entity.id)
    )
    if raw_geojson is None:
        return None
    try:
        geometry = json.loads(cast(str, raw_geojson))
    except (TypeError, json.JSONDecodeError) as exception:
        raise RuntimeError("Persisted semantic location is not valid GeoJSON") from exception
    if not isinstance(geometry, dict):
        raise RuntimeError("Persisted semantic location is not a GeoJSON object")
    return cast(dict[str, JsonValue], geometry)


def _knowledge_edge_response(edge: KnowledgeEdge) -> KnowledgeEdgeResponse:
    return KnowledgeEdgeResponse(
        id=edge.id,
        created_by_subject_id=edge.created_by_subject_id,
        source_entity_id=edge.source_entity_id,
        target_entity_id=edge.target_entity_id,
        relation_type=edge.relation_type,
        properties=cast(dict[str, JsonValue], edge.properties),
        weight=edge.weight,
        created_at=edge.created_at,
    )


def _escaped_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _records_for_run_ids(
    session: Session,
    statement: Select[tuple[RecordT]],
    run_id_column: ColumnElement[UUID],
    timestamp_column: ColumnElement[datetime],
    identifier_column: ColumnElement[UUID],
    run_ids: list[UUID],
    limit: int,
) -> tuple[list[RecordT], bool]:
    if not run_ids:
        return [], False
    page_limit = _validate_page_limit(limit)
    records = list(
        session.scalars(
            statement.where(run_id_column.in_(run_ids))
            .order_by(timestamp_column.desc(), identifier_column.desc())
            .limit(page_limit + 1)
        ).all()
    )
    return records[:page_limit], len(records) > page_limit


def _add_node(nodes: dict[str, GraphNodeResponse], node: GraphNodeResponse) -> None:
    nodes[node.id] = node


def _add_edge(edges: dict[str, GraphEdgeResponse], edge: GraphEdgeResponse) -> None:
    edges[edge.id] = edge


def _edge(source: str, target: str, relation: str) -> GraphEdgeResponse:
    return GraphEdgeResponse(
        id=f"{source}:{relation}:{target}",
        source=source,
        target=target,
        relation=relation,
    )


def _subject_node_id(subject_id: UUID) -> str:
    return f"subject:{subject_id}"


def _product_node_id(product_id: UUID) -> str:
    return f"product:{product_id}"


def _run_node_id(run_id: UUID) -> str:
    return f"run:{run_id}"


def _stage_node_id(stage_id: UUID) -> str:
    return f"stage:{stage_id}"


def _artifact_node_id(artifact_id: UUID) -> str:
    return f"artifact:{artifact_id}"


def _metric_node_id(metric_id: UUID) -> str:
    return f"metric:{metric_id}"


def _review_node_id(review_id: UUID) -> str:
    return f"review:{review_id}"


def _subject_node(subject: Subject) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_subject_node_id(subject.id),
        type="subject",
        label=subject.subject_name,
        attributes={"subject_type": subject.subject_type},
    )


def _product_node(product: Product) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_product_node_id(product.id),
        type="product",
        label=product.product_identity,
        attributes={
            "payload_type": product.payload_type,
            "validation_state": product.validation_state,
            "manifest_sha256": product.manifest_sha256,
        },
    )


def _run_node(run: Run) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_run_node_id(run.id),
        type="run",
        label=f"Run {run.id}",
        attributes={
            "execution_state": run.execution_state,
            "effective_disposition": run.effective_disposition,
            "computed_verdict": run.computed_verdict,
        },
    )


def _stage_node(stage: RunStage) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_stage_node_id(stage.id),
        type="stage",
        label=f"{stage.stage_name} (attempt {stage.attempt})",
        attributes={"execution_state": stage.execution_state, "ordinal": stage.stage_ordinal},
    )


def _artifact_node(artifact: Artifact) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_artifact_node_id(artifact.id),
        type="artifact",
        label=artifact.kind,
        attributes={"media_type": artifact.media_type, "sha256": artifact.sha256},
    )


def _metric_node(metric: Metric) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_metric_node_id(metric.id),
        type="metric",
        label=f"{metric.report_kind} v{metric.report_version}",
        attributes={"computed_verdict": metric.computed_verdict},
    )


def _review_node(review: Review) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=_review_node_id(review.id),
        type="review",
        label=review.decision,
        attributes={"reason_code": review.reason_code},
    )
