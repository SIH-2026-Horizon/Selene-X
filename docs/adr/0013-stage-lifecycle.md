# ADR-0013: Stage resume, retry, cancellation, atomic publication, and downstream invalidation

- **Status:** accepted
- **Date:** 2026-08-27
- **Blocks:** WP-01 stage runner; WP-10 job control
- **Related decisions:** R-013

## Context

A partial output must never be discoverable as a successful artefact. Resume may reuse a stage only when hashes, parameters, versions, checksums, and schemas all match, and a changed upstream input must invalidate every downstream result.

## Decision

`selene_core.pipeline.runner.StageRunner` is the one place that decides
whether a stage runs, resumes, retries, or invalidates:

- **Resume by fingerprint.** Before running a stage, `StageRunner` computes
  `stage_fingerprint` from the stage/algorithm identity and versions, the
  digested inputs, and the declared parameter subset. `_reusable` returns a
  prior `StageResult` only if it exists, its outcome is
  `is_reusable_on_resume` (a successful outcome — a `REJECTED` result is
  never cached because it is cheap to recompute and may change once its
  inputs are corrected), its fingerprint matches exactly, every one of its
  outputs is `PUBLISHED`, and `ArtifactStore.verify` confirms every output
  still matches its recorded checksum byte for byte. Any mismatch forces a
  re-run rather than a guess.
- **Downstream invalidation, structurally, not as a bookkeeping step.**
  `_input_digests` sets a stage's `input_digests[dependency]` to
  `digest_many` of its upstream's *output* digests. If an upstream stage
  produces different bytes, every stage downstream of it computes a different
  fingerprint on its next run and therefore cannot resume — invalidation is a
  consequence of the data flowing through the fingerprint, not a flag anyone
  has to remember to set.
- **Cooperative cancellation.** `CancellationToken.check()` raises
  `RunCancelled` only at a checkpoint a stage calls explicitly
  (`StageContext.checkpoint`); a cancelled attempt is recorded with outcome
  `CANCELLED`, and its scratch directory is abandoned
  (`ArtifactStore.abandon`), never published. Completed prior stages remain in
  the manifest and reusable.
- **Retry keyed by failure code, not by a fixed count alone.** `_execute`
  retries an attempt (up to `max_attempts`, default `DEFAULT_MAX_ATTEMPTS =
  3`) only while the outcome is `FAILED` *and* `is_retryable(failure.code)` is
  true. A `StageRejected` (scientific refusal) or a non-retryable `StageFailed`
  code returns immediately without consuming further attempts — deterministic
  validation and scientific gate failures never retry, because the same
  evidence will produce the same result again.
- **Atomic publication.** `_attempt` runs the stage against a fresh, isolated
  scratch directory (`ArtifactStore.scratch_for`, which removes any leftover
  directory from a prior attempt first), and any exception the stage raises —
  `StageRejected`, `StageFailed`, `RunCancelled`, or an unhandled exception —
  is caught and turned into a `StageFailure` with a stable `FailureCode`
  (`INTERNAL_UNEXPECTED_ERROR` for the unhandled case) rather than propagating
  a bare traceback. `StageRunner.run` writes the manifest after every
  non-reused stage, so an interrupted run leaves the last completed stage
  recorded and resumable, and stops at the first stage whose outcome is not a
  success.
- **A stage cannot assume it runs every invocation.** Because resume may
  return a cached `StageResult` without calling `stage.run` at all, a stage
  must not perform side effects (such as external notifications) that it
  assumes happen on every invocation; only what is captured in its
  `StageResult` is guaranteed to reflect what actually happened this run.

## Consequences

A resumed run only ever re-executes stages whose inputs, parameters, code
version, or on-disk artefacts have actually changed, so restarting after an
interruption is cheap and safe by construction rather than by operator
discipline. A stage author gets retry, cancellation, resume, and atomic
publication for free by implementing the `Stage` protocol and calling
`context.checkpoint()` between units of work; reimplementing any of those five
behaviours inside a stage is now redundant and a review rejection. A stage
that mutates state outside its declared outputs (a side effect not captured in
`StageOutput`) is now a correctness bug, because resume can silently skip
that mutation on a later run. Bumping `stage_version` is mandatory whenever a
stage's behaviour changes; forgetting to do so means a stale cached result is
wrongly reused, which is a foreseeable consequence of this design (see
ADR-0006), not a defect in the runner itself.

## Verification

`tests/unit/test_runner.py` and `tests/e2e/test_cli_noop.py`.

## Alternatives considered

Not recorded; this ADR ratifies an implementation decision already embodied in merged code rather than a forward decision with a considered alternative set.
