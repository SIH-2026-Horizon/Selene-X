"""Thin versioned HTTP routes for persisted SELENE-XR provenance state."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from selene_service.api.dependencies import CurrentIdentity, DatabaseSession
from selene_service.api.schemas import (
    ArtifactPageResponse,
    KnowledgeEdgeCreateRequest,
    KnowledgeEdgePageResponse,
    KnowledgeEdgeResponse,
    KnowledgeEntityCreateRequest,
    KnowledgeEntityPageResponse,
    KnowledgeEntityResponse,
    KnowledgeGraphResponse,
    MetricPageResponse,
    ProductCreateRequest,
    ProductPageResponse,
    ProductResponse,
    ReviewCreateRequest,
    ReviewPageResponse,
    ReviewResponse,
    RunCreateRequest,
    RunEventPageResponse,
    RunPageResponse,
    RunResponse,
    SemanticKnowledgeGraphResponse,
    StagePageResponse,
)
from selene_service.api.services import (
    cancel_run,
    crater_detail,
    crater_observations,
    create_knowledge_edge,
    create_knowledge_entity,
    create_product,
    create_run,
    get_knowledge_entity,
    get_product,
    get_run,
    knowledge_graph,
    knowledge_neighbors,
    list_artifacts,
    list_events,
    list_knowledge_edges,
    list_knowledge_entities,
    list_metrics,
    list_products,
    list_reviews,
    list_runs,
    list_stages,
    query_knowledge,
    submit_review,
)

router = APIRouter(prefix="/api/v1", tags=["provenance"])
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/products", response_model=ProductPageResponse, operation_id="list_products")
@router.get(
    "/products/catalog",
    response_model=ProductPageResponse,
    operation_id="list_product_catalog",
)
def products(
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
    validation_state: str | None = None,
    query: str | None = None,
) -> ProductPageResponse:
    """Browse persisted product catalog records."""

    return list_products(
        session,
        cursor=cursor,
        limit=limit,
        validation_state=validation_state,
        query=query,
    )


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register_product",
)
@router.post(
    "/products/register",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register_product_metadata",
)
def register_product(
    request: ProductCreateRequest,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProductResponse:
    """Register real validated product metadata; bytes stay in object storage."""

    return create_product(session, identity, request, idempotency_key)


@router.get("/products/{product_id}", response_model=ProductResponse, operation_id="get_product")
def product(product_id: UUID, session: DatabaseSession) -> ProductResponse:
    """Fetch one persisted product."""

    return get_product(session, product_id)


@router.get("/runs", response_model=RunPageResponse, operation_id="list_runs")
def runs(
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
    execution_state: str | None = None,
    query: str | None = None,
) -> RunPageResponse:
    """Browse truthful persisted lifecycle state for requested runs."""

    return list_runs(
        session,
        cursor=cursor,
        limit=limit,
        execution_state=execution_state,
        query=query,
    )


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_run",
)
def register_run(
    request: RunCreateRequest,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunResponse:
    """Persist a complete run definition and its creation provenance event."""

    return create_run(session, identity, request, idempotency_key)


@router.get("/runs/{run_id}", response_model=RunResponse, operation_id="get_run")
def run(run_id: UUID, session: DatabaseSession) -> RunResponse:
    """Fetch one persisted run definition and current state."""

    return get_run(session, run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunResponse, operation_id="cancel_run")
def cancel(
    run_id: UUID,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunResponse:
    """Request cancellation only from a lifecycle state that permits it."""

    return cancel_run(session, identity, run_id, idempotency_key)


@router.get(
    "/runs/{run_id}/stages",
    response_model=StagePageResponse,
    operation_id="list_run_stages",
)
def stages(
    run_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> StagePageResponse:
    """List runner-persisted stages (possibly empty)."""

    return list_stages(session, run_id, cursor=cursor, limit=limit)


@router.get(
    "/runs/{run_id}/artifacts",
    response_model=ArtifactPageResponse,
    operation_id="list_run_artifacts",
)
def artifacts(
    run_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> ArtifactPageResponse:
    """List runner-persisted artifact records (possibly empty)."""

    return list_artifacts(session, run_id, cursor=cursor, limit=limit)


@router.get(
    "/runs/{run_id}/metrics",
    response_model=MetricPageResponse,
    operation_id="list_run_metrics",
)
def metrics(
    run_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> MetricPageResponse:
    """List persisted metric reports (possibly empty)."""

    return list_metrics(session, run_id, cursor=cursor, limit=limit)


@router.get(
    "/runs/{run_id}/events",
    response_model=RunEventPageResponse,
    operation_id="list_run_events",
)
def events(
    run_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> RunEventPageResponse:
    """List append-only persisted lifecycle/provenance events."""

    return list_events(session, run_id, cursor=cursor, limit=limit)


@router.post(
    "/runs/{run_id}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_run_review",
)
def review(
    run_id: UUID,
    request: ReviewCreateRequest,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ReviewResponse:
    """Submit an immutable review without overwriting computed science."""

    return submit_review(session, identity, run_id, request, idempotency_key)


@router.get(
    "/runs/{run_id}/reviews",
    response_model=ReviewPageResponse,
    operation_id="list_run_reviews",
)
def reviews(
    run_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> ReviewPageResponse:
    """List immutable review history."""

    return list_reviews(session, run_id, cursor=cursor, limit=limit)


@router.get(
    "/knowledge/entities",
    response_model=KnowledgeEntityPageResponse,
    operation_id="list_knowledge_entities",
)
def semantic_entities(
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
    entity_type: str | None = None,
    external_id: str | None = None,
) -> KnowledgeEntityPageResponse:
    """Browse durable generic semantic entities."""

    return list_knowledge_entities(
        session,
        cursor=cursor,
        limit=limit,
        entity_type=entity_type,
        external_id=external_id,
    )


@router.post(
    "/knowledge/entities",
    response_model=KnowledgeEntityResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_knowledge_entity",
)
def create_semantic_entity(
    request: KnowledgeEntityCreateRequest,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> KnowledgeEntityResponse:
    """Create one explicit semantic node; the service never seeds a catalog."""

    return create_knowledge_entity(session, identity, request, idempotency_key)


@router.get(
    "/knowledge/entities/{entity_id}",
    response_model=KnowledgeEntityResponse,
    operation_id="get_knowledge_entity",
)
def semantic_entity(entity_id: UUID, session: DatabaseSession) -> KnowledgeEntityResponse:
    """Fetch one semantic entity by real UUID."""

    return get_knowledge_entity(session, entity_id)


@router.get(
    "/knowledge/entities/{entity_id}/neighbors",
    response_model=SemanticKnowledgeGraphResponse,
    response_model_exclude_none=True,
    operation_id="get_knowledge_neighbors",
)
def semantic_entity_neighbors(
    entity_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
    relation_type: str | None = None,
) -> SemanticKnowledgeGraphResponse:
    """Fetch direct persisted semantic relationships and neighboring nodes."""

    return knowledge_neighbors(
        session,
        entity_id,
        cursor=cursor,
        limit=limit,
        relation_type=relation_type,
    )


@router.get(
    "/knowledge/edges",
    response_model=KnowledgeEdgePageResponse,
    operation_id="list_knowledge_edges",
)
def semantic_edges(
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
    source_entity_id: UUID | None = None,
    target_entity_id: UUID | None = None,
    relation_type: str | None = None,
) -> KnowledgeEdgePageResponse:
    """Browse only stored semantic relationships."""

    return list_knowledge_edges(
        session,
        cursor=cursor,
        limit=limit,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type=relation_type,
    )


@router.post(
    "/knowledge/edges",
    response_model=KnowledgeEdgeResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_knowledge_edge",
)
def create_semantic_edge(
    request: KnowledgeEdgeCreateRequest,
    session: DatabaseSession,
    identity: CurrentIdentity,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> KnowledgeEdgeResponse:
    """Create a directed relationship between two existing semantic nodes."""

    return create_knowledge_edge(session, identity, request, idempotency_key)


@router.get(
    "/knowledge/query",
    response_model=SemanticKnowledgeGraphResponse,
    response_model_exclude_none=True,
    operation_id="query_knowledge",
)
def semantic_query(
    session: DatabaseSession,
    query: str | None = None,
    entity_type: str | None = None,
    relation_type: str | None = None,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> SemanticKnowledgeGraphResponse:
    """Run transparent lexical/exact-filter semantic graph retrieval."""

    return query_knowledge(
        session,
        query=query,
        entity_type=entity_type,
        relation_type=relation_type,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/knowledge/craters/{crater_id}",
    response_model=KnowledgeEntityResponse,
    operation_id="get_crater_detail",
)
def crater(crater_id: UUID, session: DatabaseSession) -> KnowledgeEntityResponse:
    """Crater-compatible entity detail sourced only from a CRATER row."""

    return crater_detail(session, crater_id)


@router.get(
    "/knowledge/craters/{crater_id}/observations",
    response_model=SemanticKnowledgeGraphResponse,
    response_model_exclude_none=True,
    operation_id="list_crater_observations",
)
def observations_for_crater(
    crater_id: UUID,
    session: DatabaseSession,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> SemanticKnowledgeGraphResponse:
    """Return persisted OBSERVATION neighbors of a CRATER, if any."""

    return crater_observations(session, crater_id, cursor=cursor, limit=limit)


@router.get(
    "/knowledge-graph",
    response_model=KnowledgeGraphResponse,
    response_model_exclude_none=True,
    operation_id="get_knowledge_graph",
)
def graph(
    session: DatabaseSession,
    center_type: Literal["run", "product"] | None = None,
    center_id: UUID | None = None,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> KnowledgeGraphResponse:
    """Return the DB-derived provenance graph around a real product or run."""

    return knowledge_graph(
        session,
        center_type=center_type,
        center_id=center_id,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/registration-graphs",
    response_model=KnowledgeGraphResponse,
    response_model_exclude_none=True,
    operation_id="get_registration_provenance_graph",
)
def registration_graph(
    session: DatabaseSession,
    center_type: Literal["run", "product"] | None = None,
    center_id: UUID | None = None,
    cursor: str | None = None,
    limit: PageLimit = 50,
) -> KnowledgeGraphResponse:
    """Return the separate DB-derived registration provenance projection."""

    return knowledge_graph(
        session,
        center_type=center_type,
        center_id=center_id,
        cursor=cursor,
        limit=limit,
    )
