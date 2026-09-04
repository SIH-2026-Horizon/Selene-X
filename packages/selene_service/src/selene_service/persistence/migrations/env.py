"""Alembic environment for the PostgreSQL/PostGIS service-state schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from selene_service.persistence.models import Base
from selene_service.settings import ServiceSettings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _explicit_database_url() -> str:
    """Validate the URL required to run a schema-changing command.

    Alembic intentionally has no fallback URL.  Operators must explicitly set
    ``SELENE_SERVICE_DATABASE_URL`` so a migration cannot silently target the
    development default database.
    """

    database_url = os.environ.get("SELENE_SERVICE_DATABASE_URL")
    if database_url is None or not database_url.strip():
        raise RuntimeError(
            "SELENE_SERVICE_DATABASE_URL is required for Alembic commands; "
            "use a dedicated PostgreSQL/PostGIS database."
        )
    return str(ServiceSettings.model_validate({"database_url": database_url}).database_url)


def run_migrations_offline() -> None:
    """Generate SQL without opening a connection."""

    context.configure(
        url=_explicit_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply revisions to the explicitly configured PostgreSQL/PostGIS target."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _explicit_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
