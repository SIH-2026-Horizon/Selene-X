"""Database composition and transaction seams for the service layer.

Importing this module never opens a database connection.  Applications and
tests deliberately choose when to construct an engine from ``ServiceSettings``
or an explicit database URL.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Protocol, TypeVar

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from selene_service.settings import ServiceSettings


SessionFactory = sessionmaker[Session]


class ServiceDatabaseUrlError(ValueError):
    """Raised when service persistence is configured for a non-PostgreSQL backend."""


class TransactionalSession(Protocol):
    """Small transaction protocol shared by real sessions and unit-test seams."""

    def add(self, instance: object) -> None:
        """Stage an ORM object in the active transaction."""

    def begin(self) -> AbstractContextManager[object]:
        """Start a transaction context."""

    def close(self) -> None:
        """Release session resources after the unit of work."""


SessionType = TypeVar("SessionType", bound=TransactionalSession)


def create_service_engine(database_url: str | URL, *, echo: bool = False) -> Engine:
    """Create an unconnected PostgreSQL engine for an explicitly supplied URL.

    SQLite and other dialects cannot provide the PostgreSQL/PostGIS schema or
    transaction guarantees in ADR-0014, so they fail before an engine exists.
    """

    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise ServiceDatabaseUrlError("SELENE-XR service persistence requires a PostgreSQL URL")

    return create_engine(parsed_url, echo=echo, pool_pre_ping=True)


def create_engine_from_settings(settings: ServiceSettings, *, echo: bool = False) -> Engine:
    """Compose an unconnected engine from typed settings at application startup."""

    return create_service_engine(str(settings.database_url), echo=echo)


def create_session_factory(engine: Engine) -> SessionFactory:
    """Return a per-request/per-test session factory without opening a connection."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def atomic_unit_of_work(
    session_factory: Callable[[], SessionType],
) -> Generator[SessionType, None, None]:
    """Provide an explicit transaction for callers that do not own one already.

    Repository methods never commit.  A caller may either use this context or
    pass a session inside its own ``session.begin()`` transaction, making all
    related event and state writes one atomic database operation.
    """

    session = session_factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
