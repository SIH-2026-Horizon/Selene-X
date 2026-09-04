# Runbooks

Operational procedures for running, diagnosing, and validating the pipeline.
Available runbooks:

- [local platform foundation](local-platform.md) — local PostGIS, MinIO,
  migrations, and service startup with loopback-only Docker publication
- [session-auth integration evidence](session-auth-integration-evidence.md) —
  recorded local verification of session roles and unauthenticated fallback

Planned runbooks:

- acquiring benchmark data and verifying integrity against a manifest
- furnishing and verifying SPICE kernel coverage
- diagnosing a quarantined product and re-validating it after correction
- interpreting a `review` verdict and recording a review decision
- validating an output bundle without running the pipeline
- reproducing a frozen benchmark run in a clean environment
