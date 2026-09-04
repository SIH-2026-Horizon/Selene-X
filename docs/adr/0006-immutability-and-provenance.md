# ADR-0006: Immutable inputs, stage results, and provenance hashing

- **Status:** accepted
- **Date:** 2026-08-27
- **Blocks:** WP-01 artefact protocol; WP-09 manifests; resume and audit behaviour
- **Related decisions:** R-015

## Context

Original input bytes and geometry are immutable and corrected outputs are named derived variants. Resume, audit, and claim traceability all depend on a stable hashing scheme over inputs, parameters, code revision, and outputs.

## Decision

Content identity, publication, and result immutability are each implemented
by one module with one rule:

- **Hashing** (`selene_core.pipeline.hashing`): every fingerprint is a
  SHA-256 hex digest of a canonical JSON form — UTF-8, sorted keys, no
  insignificant whitespace, floats serialised by `repr` round-tripping, and a
  `ValueError` if a non-finite float is present (a missing value must be
  `null` with a reason, never `NaN`/`inf` hashed as if it were data).
  `digest_json` hashes any JSON-serialisable value this way; `digest_file`
  streams a file's bytes through the same digest so large products never load
  fully into memory; `digest_many` combines several digests order-independently
  (inputs are sorted first) so that discovery order never changes a fingerprint.
- **Publication** (`selene_core.pipeline.artifacts`): every artefact is
  written to scratch, fsynced, checksummed, optionally schema-validated, then
  moved into `artifacts/` with `os.replace` (atomic within one filesystem) and
  the destination directory fsynced. `ArtifactStore.publish` refuses to
  overwrite anything already at its destination path — a published artefact
  is immutable, and a re-run publishes to a new path under its own attempt
  number, leaving the prior artefact as history. `ArtifactStore.verify`
  recomputes size and digest and raises `ArtifactVerificationError` on any
  mismatch, which is what makes a tampered or truncated artefact detectable
  without rerunning the pipeline.
- **Stage results** (`selene_core.pipeline.results`): `StageResult` and
  `ArtifactRef` are frozen, extra-field-forbidding Pydantic models
  (`model_config = ConfigDict(frozen=True, extra="forbid", ...)`). A
  `StageResult`'s validators reject a success that carries a `failure`, a
  non-success without one, a `SUCCEEDED` result that carries warnings (must be
  `SUCCEEDED_WITH_WARNINGS`), a successful result with an unpublished output,
  and a non-SHA-256 input digest. `stage_fingerprint` hashes exactly the
  stage/algorithm identity, versions, input digests, and the declared
  parameter subset — deliberately excluding `code_revision`, wall-clock times,
  and attempt number, so a behaviourally-inert commit does not invalidate a
  cached result, and any stage whose behaviour does change is required to
  bump `stage_version` to invalidate it.

## Consequences

Resume can trust a fingerprint match without re-reading every upstream byte
manually, because `ArtifactRef.sha256` plus `ArtifactStore.verify` make a
manifest's claim about an artefact's content independently checkable at any
later time. A stage can never publish a partial or half-written result under
its final name — only `atomic_write`/`ArtifactStore.publish`'s
scratch-then-replace sequence reaches `artifacts/`, so writing a file directly
into the published tree from stage code is now a review rejection. Constructing
a `StageResult` or `ArtifactRef` with a mismatched outcome/failure pair, an
unpublished output on a successful stage, or a non-hex-digest checksum is a
`ValidationError` at construction time, not a bug discovered downstream. Editing
a `StageResult` after construction is impossible (`frozen=True`); correcting a
result means producing a new one. A stage that changes behaviour without
bumping `stage_version` will have its stale result wrongly reused on resume —
this is a documented trade-off of the fingerprint's exclusion list, not a gap
covered by this module.

## Verification

`tests/unit/test_hashing.py`, `tests/unit/test_artifacts.py`, and
`tests/unit/test_results.py`.

## Alternatives considered

Not recorded; this ADR ratifies an implementation decision already embodied in merged code rather than a forward decision with a considered alternative set.
