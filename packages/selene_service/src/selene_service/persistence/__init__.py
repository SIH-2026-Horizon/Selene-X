"""PostgreSQL/PostGIS persistence: the sole service-state authority (ADR-014).

Minimum entities from plan section 5.4: ``subjects``/``api_keys``, ``products``,
``runs``, ``run_stages``, ``artifacts``, ``metrics``, ``reviews``,
``idempotency_records``, and ``run_events``.

A state transition and its corresponding event, artefact registration, metric
registration, or review record commit in one database transaction. Image bytes
stay in a filesystem or S3-compatible store; the database records only
validated published objects. Migrations are versioned and integration-tested
against a real PostgreSQL/PostGIS instance.
"""

from selene_service.persistence.models import Base
from selene_service.persistence.repositories import (
    ConcurrentReviewSubmissionError,
    ConcurrentRunTransitionError,
    NewRun,
    ReservedEventDocumentFieldError,
    RunRepository,
)
from selene_service.persistence.session import (
    ServiceDatabaseUrlError,
    atomic_unit_of_work,
    create_engine_from_settings,
    create_service_engine,
    create_session_factory,
)

__all__ = [
    "Base",
    "ConcurrentReviewSubmissionError",
    "ConcurrentRunTransitionError",
    "NewRun",
    "ReservedEventDocumentFieldError",
    "RunRepository",
    "ServiceDatabaseUrlError",
    "atomic_unit_of_work",
    "create_engine_from_settings",
    "create_service_engine",
    "create_session_factory",
]
