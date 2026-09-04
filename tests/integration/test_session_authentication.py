"""Opt-in real PostgreSQL verification of the login/session HTTP round trip."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

from selene_service.api.password_auth import hash_password
from selene_service.app import create_app
from selene_service.persistence.models import Base, Subject, UserAccount
from selene_service.settings import AuthenticationMode, ServiceSettings

# Reuses the `postgres_engine` fixture from the root tests/conftest.py (added in
# Task 4): it skips this test cleanly if SELENE_SERVICE_TEST_DATABASE_URL is
# unset, and yields a real Engine against an already-migrated database. Unlike
# tests/integration/test_postgres_persistence.py, no alembic upgrade/check call
# is needed here — the engine is expected to already be at head, and this test
# only exercises real CRUD/session behaviour through the HTTP layer, not
# schema-drift detection.
#
# create_app(settings) is handed the real database URL (rather than a
# session-factory override applied after the fact) so that its own lifespan
# builds its engine/session factory against the real test database and runs
# bootstrap_admin_user (Step 9a) against it, creating the account this test
# logs in as.

pytestmark = pytest.mark.integration


def _delete_test_account(engine: Engine, *, username: str) -> None:
    """Idempotently remove one session-auth test identity and its rows.

    Called both before a test creates its account (self-healing if a prior
    run was interrupted before its own cleanup ran) and after a test
    finishes (so nothing durable lingers for the next run). This file's
    tests commit real rows against a persistent, shared sibling test
    database rather than rolling back at teardown, so without this a
    left-behind ``user_accounts`` row would keep its ``subjects`` row alive
    (FK-referenced) for `tests/unit/test_session_auth.py`'s own cleanup
    fixture, whose ``subject_name LIKE 'user:%'`` clause is broader than the
    handful of usernames it deletes from ``user_accounts`` — tripping a
    foreign-key violation there instead of here.
    """

    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM user_sessions WHERE user_account_id IN "
                "(SELECT id FROM user_accounts WHERE username = :username)"
            ),
            {"username": username},
        )
        connection.execute(
            text("DELETE FROM user_accounts WHERE username = :username"),
            {"username": username},
        )
        connection.execute(
            text("DELETE FROM subjects WHERE subject_name = :subject_name"),
            {"subject_name": f"user:{username}"},
        )


def test_login_then_authenticated_request_then_logout_round_trip(postgres_engine: Engine) -> None:
    username = "integration-admin"
    Base.metadata.create_all(postgres_engine)
    _delete_test_account(postgres_engine, username=username)
    try:
        settings = ServiceSettings.model_validate(
            {
                "bind_host": "127.0.0.1",
                "authentication_mode": AuthenticationMode.SESSION,
                "database_url": postgres_engine.url.render_as_string(hide_password=False),
                "bootstrap_admin_username": username,
                "bootstrap_admin_password": "an-actually-strong-bootstrap-password",
            }
        )
        app = create_app(settings)

        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": username,
                    "password": "an-actually-strong-bootstrap-password",
                },
            )
            assert login.status_code == 200

            # Capture the actual session id the server issued before anything
            # clears it client-side, so it can be re-attached after logout below.
            session_cookie = client.cookies.get(settings.session_cookie_name)
            assert session_cookie is not None

            session_response = client.get("/api/v1/auth/session")
            assert session_response.status_code == 200
            assert session_response.json()["role"] == "admin"

            logout = client.post("/api/v1/auth/logout")
            assert logout.status_code == 204

            # `logout_route`'s `response.delete_cookie` has already cleared this
            # cookie from the TestClient's jar, so a plain follow-up request
            # would return 401 merely because the client has nothing to send —
            # that would not prove the session was revoked *server-side*.
            # Re-attach the captured session id explicitly to prove the session
            # itself is now rejected, not just that the client lost its cookie.
            client.cookies.set(settings.session_cookie_name, session_cookie)
            after_logout = client.get("/api/v1/auth/session")
            assert after_logout.status_code == 401
    finally:
        _delete_test_account(postgres_engine, username=username)


def test_repeated_failed_logins_lock_the_account_and_the_lockout_write_survives(
    postgres_engine: Engine,
) -> None:
    """Regression test: ``auth_services.login()`` used to raise the 401
    ``APIProblem`` from *inside* its own ``with session.begin():`` block,
    which rolled the whole transaction back — including
    ``record_login_failure``'s counter/lockout writes that
    ``authenticate_with_password`` had already flushed. The lockout
    mechanism itself was correct; only the transaction boundary in
    ``login()`` discarded its effects, so the account never actually
    locked. This must go through the real HTTP ``/api/v1/auth/login`` route
    against real Postgres (not ``authenticate_with_password()`` directly,
    and not the fake-session doubles in ``tests/unit/test_auth_routes.py``/
    ``test_auth_admin_routes.py``, whose ``begin()`` is a no-op
    ``contextlib.nullcontext()`` that cannot reproduce a real rollback) —
    that combination is exactly why this bug was invisible to the existing
    suite.
    """

    username = "lockout-regression-operator"
    password = "correct horse battery staple"  # noqa: S105 - not a real credential

    Base.metadata.create_all(postgres_engine)
    _delete_test_account(postgres_engine, username=username)

    try:
        factory = sessionmaker(bind=postgres_engine)
        setup_session = factory()
        try:
            subject = Subject(subject_name=f"user:{username}", subject_type="user", is_active=True)
            setup_session.add(subject)
            setup_session.flush()
            account = UserAccount(
                subject_id=subject.id,
                username=username,
                password_hash=hash_password(password),
                role="reviewer",
                display_name="Lockout Regression Operator",
            )
            setup_session.add(account)
            setup_session.commit()
            account_id = account.id
        finally:
            setup_session.close()

        settings = ServiceSettings.model_validate(
            {
                "bind_host": "127.0.0.1",
                "authentication_mode": AuthenticationMode.SESSION,
                "database_url": postgres_engine.url.render_as_string(hide_password=False),
                "login_lockout_threshold": 3,
                "login_lockout_seconds": 30,
            }
        )
        app = create_app(settings)

        with TestClient(app) as client:
            for _ in range(settings.login_lockout_threshold):
                response = client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "definitely-the-wrong-password"},
                )
                assert response.status_code == 401

            # Re-fetch from a fresh session to prove the failure count and
            # lockout timestamp were actually committed, not just mutated on
            # an in-memory ORM instance that later rolled back.
            verify_session = factory()
            try:
                persisted = verify_session.scalar(
                    select(UserAccount).where(UserAccount.id == account_id)
                )
                assert persisted is not None
                assert persisted.failed_login_count >= settings.login_lockout_threshold
                assert persisted.locked_until is not None
                assert persisted.locked_until > datetime.now(UTC)
            finally:
                verify_session.close()

            # The account is now locked: even the *correct* password is
            # rejected until the lockout window elapses.
            locked_response = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            assert locked_response.status_code == 401
    finally:
        _delete_test_account(postgres_engine, username=username)
