#!/usr/bin/env python3
"""Render and check the local-only SELENE-XR platform Compose profile.

This intentionally performs no Docker daemon operation: ``docker compose
config`` validates and renders the model locally. It is suitable for CI and
fails clearly when the Docker Compose v2 CLI is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
COMPOSE_FILE: Final = ROOT / "infra/compose/compose.platform.yaml"
EXAMPLE_ENV_FILE: Final = ROOT / "infra/compose/.env.platform.example"
DOCKERFILE: Final = ROOT / "infra/docker/Dockerfile.service"
SERVICE_DOCKERIGNORE: Final = ROOT / "infra/docker/Dockerfile.service.dockerignore"
WEB_DOCKERFILE: Final = ROOT / "infra/docker/Dockerfile.web"
WEB_DOCKERIGNORE: Final = ROOT / "infra/docker/Dockerfile.web.dockerignore"
WEB_NGINX_CONFIG: Final = ROOT / "infra/nginx/selene-web.conf.template"
WEB_SECURITY_HEADERS: Final = ROOT / "infra/nginx/security-headers.conf"
RUNBOOK: Final = ROOT / "docs/runbooks/local-platform.md"
COMPOSE_README: Final = ROOT / "infra/compose/README.md"
SERVICE_README: Final = ROOT / "packages/selene_service/README.md"
WEB_README: Final = ROOT / "web/README.md"
EXPECTED_SERVICES: Final = frozenset({"postgis", "minio", "migrate", "service", "web"})
REQUIRED_ENVIRONMENT: Final = frozenset(
    {
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "SELENE_BOOTSTRAP_ADMIN_USERNAME",
        "SELENE_BOOTSTRAP_ADMIN_PASSWORD",
    }
)


def _mapping(value: object) -> Mapping[str, object]:
    """Return a mapping value or an empty mapping for a malformed Compose field."""

    return value if isinstance(value, Mapping) else {}


def _run(
    command: Sequence[str],
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run a fixed, shell-free CLI command without printing its output."""

    return subprocess.run(  # noqa: S603 - fixed Docker Compose argument array.
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def _append_port_errors(
    errors: list[str],
    service_name: str,
    service: Mapping[str, object],
    expected_targets: set[int],
) -> None:
    """Require the exact loopback-only host ports for one service."""

    raw_ports = service.get("ports", [])
    if not isinstance(raw_ports, list):
        errors.append(f"{service_name} ports are not a list")
        return

    actual_targets: set[int] = set()
    for raw_port in raw_ports:
        port = _mapping(raw_port)
        if not port:
            errors.append(f"{service_name} has a non-normalized port declaration")
            continue
        if port.get("host_ip") != "127.0.0.1":
            errors.append(f"{service_name} publishes a non-loopback host port")
        target = port.get("target")
        if isinstance(target, int):
            actual_targets.add(target)
        else:
            errors.append(f"{service_name} has a port with a non-integer target")

    if actual_targets != expected_targets:
        errors.append(
            f"{service_name} published targets are {sorted(actual_targets)}, "
            f"expected {sorted(expected_targets)}"
        )


def _append_profile_errors(
    errors: list[str],
    services: Mapping[str, object],
) -> None:
    """Validate the local platform's service and dependency boundaries."""

    if set(services) != EXPECTED_SERVICES:
        errors.append(
            f"services are {sorted(services)}, expected exactly {sorted(EXPECTED_SERVICES)}"
        )
        return

    normalized_services = {name: _mapping(value) for name, value in services.items()}
    for name, service in normalized_services.items():
        if service.get("profiles") != ["platform"]:
            errors.append(f"{name} is not limited to the named platform profile")

    _append_port_errors(errors, "postgis", normalized_services["postgis"], {5432})
    _append_port_errors(errors, "minio", normalized_services["minio"], {9000, 9001})
    _append_port_errors(errors, "web", normalized_services["web"], {8080})
    if normalized_services["service"].get("ports"):
        errors.append("service must not publish a host port when web owns the API boundary")
    if normalized_services["migrate"].get("ports"):
        errors.append("migrate must not publish a host port")

    migration_depends_on = _mapping(normalized_services["migrate"].get("depends_on"))
    postgis_dependency = _mapping(migration_depends_on.get("postgis"))
    if postgis_dependency.get("condition") != "service_healthy":
        errors.append("migrate must wait for healthy postgis")

    service_depends_on = _mapping(normalized_services["service"].get("depends_on"))
    migration_dependency = _mapping(service_depends_on.get("migrate"))
    if migration_dependency.get("condition") != "service_completed_successfully":
        errors.append("service must wait for successful migration")
    if "minio" in service_depends_on:
        errors.append("service must not claim a MinIO dependency before storage integration exists")

    web_depends_on = _mapping(normalized_services["web"].get("depends_on"))
    web_service_dependency = _mapping(web_depends_on.get("service"))
    if web_service_dependency.get("condition") != "service_healthy":
        errors.append("web must wait for a healthy service")
    if "minio" in web_depends_on:
        errors.append("web must not claim a MinIO dependency before storage integration exists")
    if normalized_services["web"].get("read_only") is not True:
        errors.append("web must use a read-only root filesystem")
    if not normalized_services["web"].get("tmpfs"):
        errors.append("web must provide an explicit temporary filesystem")

    service_environment = _mapping(normalized_services["service"].get("environment"))
    if service_environment.get("SELENE_SERVICE_AUTHENTICATION_MODE") != "session":
        errors.append("service must declare the session-authenticated operator boundary")
    if service_environment.get("SELENE_SERVICE_BIND_HOST") != "0.0.0.0":  # noqa: S104
        errors.append("service must listen on Docker's container network interface")
    database_url = service_environment.get("SELENE_SERVICE_DATABASE_URL")
    if not isinstance(database_url, str) or "@postgis:5432/" not in database_url:
        errors.append("service database URL must target the internal postgis hostname")
    for variable in (
        "SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME",
        "SELENE_SERVICE_BOOTSTRAP_ADMIN_PASSWORD",
    ):
        if variable not in service_environment:
            errors.append(f"service must receive {variable}")

    if _mapping(normalized_services["web"].get("environment")):
        errors.append("web must not receive a shared API credential in session mode")


def _append_static_errors(errors: list[str]) -> None:
    """Check safety constraints that Compose's rendered model cannot express."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    for variable in REQUIRED_ENVIRONMENT:
        if f"${{{variable}:?" not in compose_text:
            errors.append(f"{variable} is not required with Compose's :? syntax")
    if ":-" in compose_text:
        errors.append("platform Compose profile must not silently default credentials")

    example_environment = EXAMPLE_ENV_FILE.read_text(encoding="utf-8")
    if "MINIO_BUCKET=selene-private" not in example_environment:
        errors.append("example environment must name the intended private MinIO bucket")
    if "replace_with_a_" not in example_environment:
        errors.append("example environment must retain non-secret credential placeholders")
    for variable in ("SELENE_BOOTSTRAP_ADMIN_USERNAME", "SELENE_BOOTSTRAP_ADMIN_PASSWORD"):
        if f"{variable}=replace_with_a_" not in example_environment:
            errors.append(f"example environment must retain the {variable} placeholder")

    dockerfile_text = DOCKERFILE.read_text(encoding="utf-8")
    for required_fragment in (
        "USER 10001:10001",
        'ENTRYPOINT ["python"]',
        'CMD ["-m", "selene_service"]',
        "uv sync --locked --no-dev --no-editable --package selene-service",
    ):
        if required_fragment not in dockerfile_text:
            errors.append(f"service Dockerfile is missing {required_fragment!r}")
    for forbidden_copy in ("COPY data", "COPY model", "COPY secrets"):
        if forbidden_copy in dockerfile_text:
            errors.append(f"service Dockerfile must not include {forbidden_copy!r}")
    for workspace_member in ("selene_core", "selene_client", "selene_service", "selene_worker"):
        copy_instruction = f"COPY packages/{workspace_member} packages/{workspace_member}"
        if copy_instruction not in dockerfile_text:
            errors.append(
                f"service Dockerfile is missing locked workspace member {workspace_member}"
            )
    runtime_stage = dockerfile_text.partition("FROM ${BASE_IMAGE} AS runtime")[2]
    for builder_only_member in ("selene_client", "selene_worker"):
        if f"packages/{builder_only_member}" in runtime_stage:
            errors.append(f"runtime image must not copy {builder_only_member} source")

    root_dockerignore = ROOT / ".dockerignore"
    if root_dockerignore.exists():
        root_ignore_text = root_dockerignore.read_text(encoding="utf-8")
        for training_input in ("packages/selene_core", "train", "data"):
            if f"{training_input}/" in root_ignore_text:
                errors.append(
                    f"root .dockerignore excludes training build input {training_input!r}"
                )
    service_dockerignore = SERVICE_DOCKERIGNORE.read_text(encoding="utf-8")
    for excluded_path in (".env.*", "secrets/", "data/", "model/", "train/"):
        if excluded_path not in service_dockerignore:
            errors.append(f"service Dockerfile-specific ignore lacks {excluded_path!r}")

    web_dockerfile_text = WEB_DOCKERFILE.read_text(encoding="utf-8")
    for required_fragment in (
        "pnpm install --frozen-lockfile",
        "VITE_SELENE_API_BASE_URL=/api/v1",
        "VITE_SELENE_ARTIFACT_HOSTS",
        "USER nginx",
        'ENTRYPOINT ["/usr/local/bin/selene-web-entrypoint"]',
        "COPY --from=builder /app/dist /usr/share/nginx/html",
    ):
        if required_fragment not in web_dockerfile_text:
            errors.append(f"web Dockerfile is missing {required_fragment!r}")
    web_dockerignore = WEB_DOCKERIGNORE.read_text(encoding="utf-8")
    for excluded_path in (".env.*", "secrets/", "data/", "model/", "web/node_modules/"):
        if excluded_path not in web_dockerignore:
            errors.append(f"web Dockerfile-specific ignore lacks {excluded_path!r}")

    web_nginx_text = WEB_NGINX_CONFIG.read_text(encoding="utf-8")
    for required_fragment in (
        "location /api/",
        "proxy_pass http://service:8000",
        "location = /healthz",
        "location = /readyz",
        "try_files $uri $uri/ /index.html",
        "max-age=31536000, immutable",
        "Cache-Control \"no-store\"",
    ):
        if required_fragment not in web_nginx_text:
            errors.append(f"web nginx configuration is missing {required_fragment!r}")
    if "Access-Control-Allow-Origin" in web_nginx_text:
        errors.append("web nginx configuration must not add a CORS allow-origin header")
    if "X-SELENE-API-Key" in web_nginx_text:
        errors.append("web nginx configuration must not inject an API key in session mode")
    entrypoint_text = (ROOT / "infra/nginx/selene-web-entrypoint.sh").read_text(encoding="utf-8")
    for required_fragment in ("umask 077", "selene-web.conf.template", "default.conf"):
        if required_fragment not in entrypoint_text:
            errors.append(f"web entrypoint is missing {required_fragment!r}")
    if "SELENE_WEB_PROXY_API_KEY" in entrypoint_text:
        errors.append("web entrypoint must not read a shared API key in session mode")
    security_headers = WEB_SECURITY_HEADERS.read_text(encoding="utf-8")
    for required_fragment in (
        "Content-Security-Policy",
        "__SELENE_ARTIFACT_SOURCES__",
        "X-Content-Type-Options",
        "X-Frame-Options",
    ):
        if required_fragment not in security_headers:
            errors.append(f"web security headers are missing {required_fragment!r}")

    if not RUNBOOK.is_file():
        errors.append("docs/runbooks/local-platform.md is missing")
    for document in (COMPOSE_README, SERVICE_README, WEB_README):
        if "local-platform.md" not in document.read_text(encoding="utf-8"):
            errors.append(f"{document.relative_to(ROOT)} does not link the local platform runbook")


def main() -> int:
    """Render the example configuration and return a CI-friendly status code."""

    docker = shutil.which("docker")
    if docker is None:
        print(
            "Docker Compose validation unavailable: install Docker with the Compose v2 plugin. "
            "This check did not pass.",
            file=sys.stderr,
        )
        return 2

    environment = os.environ.copy()
    # A developer's ambient shell credentials must not affect CI validation or
    # cause a secret-bearing rendered configuration to be printed on failure.
    for variable in REQUIRED_ENVIRONMENT:
        environment.pop(variable, None)

    version_result = _run((docker, "compose", "version"), environment)
    if version_result.returncode != 0:
        print(
            "Docker Compose validation unavailable: Docker Compose v2 is required. "
            "This check did not pass.",
            file=sys.stderr,
        )
        return 2

    render_result = _run(
        (
            docker,
            "compose",
            "--env-file",
            str(EXAMPLE_ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "platform",
            "config",
            "--format",
            "json",
        ),
        environment,
    )
    if render_result.returncode != 0:
        print("Docker Compose could not render the local platform profile.", file=sys.stderr)
        print(render_result.stderr, file=sys.stderr)
        return 1

    try:
        rendered = json.loads(render_result.stdout)
    except json.JSONDecodeError as decode_error:
        print(f"Docker Compose did not emit JSON: {decode_error}", file=sys.stderr)
        return 1

    errors: list[str] = []
    rendered_mapping = _mapping(rendered)
    services = _mapping(rendered_mapping.get("services"))
    _append_profile_errors(errors, services)

    volumes = _mapping(rendered_mapping.get("volumes"))
    expected_volumes = {"selene-postgis-data", "selene-minio-data"}
    if set(volumes) != expected_volumes:
        errors.append(f"named volumes are {sorted(volumes)}, expected {sorted(expected_volumes)}")

    _append_static_errors(errors)
    if errors:
        print("Local platform Compose validation failed:", file=sys.stderr)
        for validation_error in errors:
            print(f"- {validation_error}", file=sys.stderr)
        return 1

    print("Local platform Compose configuration validated without starting containers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
