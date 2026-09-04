"""Shared pytest configuration.

Fixtures that require an uncommitted benchmark product must be marked
``requires_data``; fixtures needing an accelerator must be marked
``requires_gpu``. Markers are declared in the root ``pyproject.toml``.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine

from selene_service.persistence.session import create_service_engine


def _test_database_url() -> str:
    database_url = os.environ.get("SELENE_SERVICE_TEST_DATABASE_URL")
    if database_url is None or not database_url.strip():
        pytest.skip(
            "SELENE_SERVICE_TEST_DATABASE_URL is not set; "
            "real PostgreSQL/PostGIS verification is opt-in."
        )
    return database_url


@pytest.fixture
def postgres_engine() -> Generator[Engine, None, None]:
    """A real Postgres engine for opt-in integration-style tests.

    Mirrors ``tests/integration/test_postgres_persistence.py``'s
    ``create_service_engine``/skip-if-unset connection pattern, but
    deliberately omits that file's ``alembic.command.check()`` schema-drift
    guard: that guard currently has a pre-existing false positive against
    PostGIS's own ``spatial_ref_sys`` table, unrelated to anything built on
    top of this fixture. Callers are expected to run against an
    already-migrated database (``alembic upgrade head``) and only need real
    CRUD/session/transaction behavior, not drift detection.

    Placed here (the tree-wide root conftest) rather than in
    ``tests/integration/conftest.py`` so it is visible to tests under
    ``tests/unit/`` too — pytest only auto-loads a directory's own and its
    ancestors' ``conftest.py`` files, not a sibling directory's.
    """

    database_url = _test_database_url()
    engine = create_service_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
