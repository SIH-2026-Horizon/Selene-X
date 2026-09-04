# Benchmarks

Data and benchmark governance (WP-00). Evidence comes before algorithm claims.

```
manifests/   product IDs, hashes, splits, control uncertainty, route matrix
expected/    schema-level and small numeric expectations
scripts/     acquisition checks, governance validation, and the benchmark runner
```

Non-negotiable rules:

- Mission products, credentials, SPICE kernels, and model weights are never
  committed. Git stores manifests, checksums, acquisition instructions, small
  permitted fixtures, and expected results.
- Spatially related crops, repeated acquisitions, and products from the same
  local terrain group stay in one split. Held-out scenes are never used for
  parameter tuning.
- The runner emits a schema-valid report even when an algorithm fails, and
  records failed and rejected scenes rather than dropping them from
  success-rate denominators.
- Synthetic controlled-shift fixtures are labelled synthetic. A synthetic result
  can never pass a real-data route gate.
- Every quantitative claim in the README or the presentation links to a
  benchmark run ID and an immutable report through the claim ledger. The
  initial [claim ledger](claim-ledger.v1.json) authorizes no public numerical
  claims.

The provisional route-qualification gates (source-frame `RMSE_2D < 1.0` pixel,
stretch `RMSE_2D <= 0.5` pixel, eligible occupancy at least 70 percent in an
8 by 8 grid) stay provisional until D-001 and D-007 are resolved.

The [interim product-route matrix](manifests/interim-public-product-route-matrix.v1.json)
is intentionally a limitation record, not a stand-in dataset: product IDs,
URLs, licences, checksums, labels, kernels, calibration references, and scene
measurements stay null with a reason until they are verified from external
official records. It covers OHRC, TMC-2, IIRS, LROC NAC, SELENE TC, and the
SLDEM/LOLA/regional-NAC-DTM terrain candidates. Known values require a
retrievable citation, retrieval timestamp, and checksum of the evidence record;
credential requirements are stored separately without secrets.

The independent review process is defined in the
[checkpoint protocol](governance/independent-checkpoint-protocol.v1.md). It
requires independent review, records covariance/control uncertainty and
disagreement, and prohibits using held-out scenes for any tuning decision.
