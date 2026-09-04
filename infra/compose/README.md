# Local container profiles

## Platform foundation

`compose.platform.yaml` is the local single-user platform foundation for
PostGIS, an independent MinIO instance, a one-shot Alembic migration job,
`selene_service`, and a static same-origin web console at
`http://127.0.0.1:8080`. It is separate from the training profile below. Start with the
[local platform runbook](../../docs/runbooks/local-platform.md): it covers the
ignored required environment file, CI-safe Compose validation, local-only
loopback port boundary, migrations, same-origin checks, real metadata
registration, MinIO's current non-integration, credential rotation, and state
removal.

The profile is not production infrastructure and implements neither OIDC/
Keycloak nor storage integration, distributed workers, scientific processing,
retention, observability, or failover. It provisions one local Admin from the
ignored environment file; that operator can then create the Analyst and
Reviewer accounts used by the console. Invoke it only with
`--env-file infra/compose/.env.platform --profile platform` and do not expose
any mapping beyond `127.0.0.1`.

The image references use explicit version tags; they are still mutable registry
tags rather than verified digest pins. Do not substitute guessed digests. A
future provenance review can introduce verified multi-architecture digests.

## Model training

`compose.models.yaml` builds the training image, mounts `data/` as the Hugging
Face/local dataset cache, and mounts `model/` as the versioned artifact
registry.

```bash
docker compose -f infra/compose/compose.models.yaml build
docker compose -f infra/compose/compose.models.yaml run --rm trainer \
  train \
  --config /workspace/train/configs/selene_matcher.json \
  --dataset hf://your-account/selene-xr-matcher \
  --version local-dev \
  --model-root /models
```

The broader identity-provider and distributed platform profile remains a later
deliverable.
