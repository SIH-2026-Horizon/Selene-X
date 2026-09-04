"""Static contracts for the local-only Docker platform foundation."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infra/compose/compose.platform.yaml"
DOCKERFILE = ROOT / "infra/docker/Dockerfile.service"
SERVICE_DOCKERIGNORE = ROOT / "infra/docker/Dockerfile.service.dockerignore"
WEB_DOCKERFILE = ROOT / "infra/docker/Dockerfile.web"
WEB_DOCKERIGNORE = ROOT / "infra/docker/Dockerfile.web.dockerignore"
WEB_NGINX_CONFIG = ROOT / "infra/nginx/selene-web.conf.template"
WEB_SECURITY_HEADERS = ROOT / "infra/nginx/security-headers.conf"
TRAINING_DOCKERFILE = ROOT / "infra/docker/Dockerfile.training"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
EXAMPLE_ENV = ROOT / "infra/compose/.env.platform.example"
RUNBOOK = ROOT / "docs/runbooks/local-platform.md"
VALIDATOR = ROOT / "scripts/validate_platform_compose.py"


@pytest.mark.unit
def test_platform_profile_has_only_the_expected_local_services() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    for service in ("postgis", "minio", "migrate", "service", "web"):
        assert f"  {service}:" in compose
    assert compose.count('profiles: ["platform"]') == 5
    assert "  worker:" not in compose
    assert "  keycloak:" not in compose
    assert "  redis:" not in compose
    assert "  rabbitmq:" not in compose
    assert "network_mode: host" not in compose


@pytest.mark.unit
def test_platform_ports_are_explicitly_loopback_only() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert '"127.0.0.1:5432:5432"' in compose
    assert '"127.0.0.1:9000:9000"' in compose
    assert '"127.0.0.1:9001:9001"' in compose
    assert '"127.0.0.1:8080:8080"' in compose
    assert '"5432:5432"' not in compose
    assert '"9000:9000"' not in compose
    assert '"9001:9001"' not in compose
    assert '"8080:8080"' not in compose


@pytest.mark.unit
def test_platform_requires_credentials_and_orders_migrations() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    for variable in (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "SELENE_BOOTSTRAP_ADMIN_USERNAME",
        "SELENE_BOOTSTRAP_ADMIN_PASSWORD",
    ):
        assert f"${{{variable}:?" in compose
    assert ":-" not in compose
    assert "condition: service_healthy" in compose
    assert "condition: service_completed_successfully" in compose
    assert "@postgis:5432/" in compose
    assert "SELENE_SERVICE_AUTHENTICATION_MODE: session" in compose
    assert "SELENE_SERVICE_BIND_HOST: 0.0.0.0" in compose
    assert "SELENE_SERVICE_LOCAL_API_KEY" not in compose
    assert "SELENE_WEB_PROXY_API_KEY" not in compose
    assert "VITE_SELENE_ARTIFACT_HOSTS: ${VITE_SELENE_ARTIFACT_HOSTS}" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose


@pytest.mark.unit
def test_service_image_is_non_root_and_uses_the_controlled_launcher() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = SERVICE_DOCKERIGNORE.read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --no-editable --package selene-service" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["python"]' in dockerfile
    assert 'CMD ["-m", "selene_service"]' in dockerfile
    for forbidden_copy in ("COPY data", "COPY model", "COPY secrets"):
        assert forbidden_copy not in dockerfile
    for workspace_member in ("selene_core", "selene_client", "selene_service", "selene_worker"):
        assert f"COPY packages/{workspace_member} packages/{workspace_member}" in dockerfile
    runtime_stage = dockerfile.partition("FROM ${BASE_IMAGE} AS runtime")[2]
    assert "packages/selene_client" not in runtime_stage
    assert "packages/selene_worker" not in runtime_stage
    for excluded_path in (".env.*", "secrets/", "data/", "model/", "train/"):
        assert excluded_path in dockerignore


@pytest.mark.unit
def test_service_ignore_preserves_training_context_and_ci_builds_images() -> None:
    training_dockerfile = TRAINING_DOCKERFILE.read_text(encoding="utf-8")
    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    root_dockerignore = ROOT / ".dockerignore"
    if root_dockerignore.exists():
        root_ignore = root_dockerignore.read_text(encoding="utf-8")
        for training_input in ("packages/selene_core", "train", "data"):
            assert f"{training_input}/" not in root_ignore
    assert "COPY packages/selene_core" in training_dockerfile
    assert "COPY train" in training_dockerfile
    assert "COPY data" in training_dockerfile
    assert "COPY LICENSE /workspace/LICENSE" in training_dockerfile
    assert "docker build --file infra/docker/Dockerfile.service" in ci_workflow
    assert "docker build --file infra/docker/Dockerfile.training" in ci_workflow


@pytest.mark.unit
def test_web_image_is_locked_static_same_origin_and_restricts_artifact_origins() -> None:
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = WEB_DOCKERIGNORE.read_text(encoding="utf-8")
    nginx = WEB_NGINX_CONFIG.read_text(encoding="utf-8")
    headers = WEB_SECURITY_HEADERS.read_text(encoding="utf-8")

    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "VITE_SELENE_API_BASE_URL=/api/v1" in dockerfile
    assert "VITE_SELENE_ARTIFACT_HOSTS" in dockerfile
    assert "USER nginx" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/selene-web-entrypoint"]' in dockerfile
    assert "COPY --from=builder /app/dist /usr/share/nginx/html" in dockerfile
    for excluded_path in (".env.*", "secrets/", "data/", "model/", "web/node_modules/"):
        assert excluded_path in dockerignore
    assert "location /api/" in nginx
    assert "resolver 127.0.0.11 ipv6=off" in nginx
    assert "set $selene_service service" in nginx
    assert "proxy_pass http://$selene_service:8000" in nginx
    assert "location = /healthz" in nginx
    assert "location = /readyz" in nginx
    assert "X-SELENE-API-Key" not in nginx
    assert 'X-SELENE-Subject ""' not in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "max-age=31536000, immutable" in nginx
    assert "Access-Control-Allow-Origin" not in nginx
    assert "Content-Security-Policy" in headers
    assert "__SELENE_ARTIFACT_SOURCES__" in headers


@pytest.mark.unit
def test_platform_documentation_and_ci_safe_validator_are_present() -> None:
    template = EXAMPLE_ENV.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    validator = VALIDATOR.read_text(encoding="utf-8")

    assert "replace_with_a_unique_url_safe_local_password" in template
    assert "MINIO_BUCKET=selene-private" in template
    assert "mc mb --ignore-existing local/selene-private" in runbook
    assert "--env-file infra/compose/.env.platform" in runbook
    assert "docker compose" in runbook
    assert "down --volumes" in runbook
    assert "local single-user development" in runbook
    assert "bootstrap Admin credentials" in runbook
    assert "Argon2id password hash" in runbook
    assert "Nginx proxy forwards" in runbook
    assert "SELENE_SESSION_JAR" in runbook
    assert "/api/v1/auth/login" in runbook
    assert "X-SELENE-API-Key" in runbook
    assert "--arg password" not in runbook
    assert "jq receives both values only on standard input" in runbook
    assert "mutable tags" in runbook
    assert '"compose",' in validator
    assert '"config",' in validator
    assert "without starting containers" in validator
