# Schemas

JSON Schemas for inputs, parameters, outputs, metrics, provenance, and verdicts
(WP-01 task 5). Section 6 of the implementation plan is the source of truth for
their content.

Every schema is a concrete Draft 2020-12 contract. Object contracts reject
unknown fields; scientific parameter blocks are closed vocabulary, so a typo
cannot silently alter a run. A metric that cannot be computed is recorded as
`null` with a non-empty reason rather than a fabricated zero.

A provenance manifest is a complete output-bundle identity, not an artifact
list: it records checksummed inputs, reference/control status, a closed
parameter snapshot, model and dependency declarations, code revision, and a
reproducible environment identity. A genuinely unavailable model, dependency,
or control source must say why rather than disappearing from the record.

| File | Contract | Plan reference |
| --- | --- | --- |
| `product-input-manifest.schema.json` | Source and reference product record | 6.2 |
| `reference-bundle-manifest.schema.json` | Reference, terrain, and control bundle | 6.3 |
| `correspondence-record.schema.json` | Canonical match record | 6.4 |
| `stage-result.schema.json` | Immutable stage result protocol | 6.5 |
| `metric-report.schema.json` | Route-qualification and scene reports | 6.6 |
| `parameter-set.schema.json` | Versioned scientific parameters | WP-01 task 5 |
| `provenance-manifest.schema.json` | Output bundle provenance | WP-09 task 7 |
| `verdict.schema.json` | Gates, computed verdict, disposition | 8, 10 |
| `failure-envelope.schema.json` | Stable failure taxonomy | WP-09 task 8 |
| `benchmark-manifest.schema.json` | Benchmark products, splits, stress bins | WP-00 task 1 |

`stage-result`, `correspondence-record`, and `verdict` are generated from their
public Pydantic contracts and checked for exact schema/model agreement. The
remaining document contracts are intentionally schema-first until their owning
work packages introduce public typed constructors; their positive and negative
examples live in `tests/unit/test_schemas.py`.
