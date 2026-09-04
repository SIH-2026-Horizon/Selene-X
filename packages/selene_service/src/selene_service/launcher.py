"""Controlled process launcher that binds only to validated service settings."""

from __future__ import annotations

import uvicorn

from selene_service.app import create_app
from selene_service.settings import ServiceSettings


def run_service(settings: ServiceSettings | None = None) -> None:
    """Start the service using its validated configured bind host and port.

    This is intentionally the supported executable path rather than a Uvicorn
    command with independently supplied ``--host`` and ``--port`` flags. The
    factory validates the exact host passed to Uvicorn before a socket can be
    opened.
    """

    configured_settings = settings or ServiceSettings()
    application = create_app(configured_settings)
    uvicorn.run(
        application,
        host=configured_settings.bind_host,
        port=configured_settings.port,
    )
