"""A no-op stage that exercises the runner contract (WP-01 task 11).

This stage does no science. It exists so that packaging, configuration, atomic
result writing, resume, cancellation, retry, and error propagation can be proved
before any scientific code depends on them. ``selene noop`` drives it from the
command line, and the integration tests drive it directly.

It is shipped rather than confined to the test tree because the same fixture
needs to run from an installed wheel in a clean environment, which is one of
WP-01's exit criteria.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum

from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.results import StageWarning
from selene_core.pipeline.runner import (
    StageContext,
    StageFailed,
    StageOutput,
    StageRejected,
)

__all__ = ["NoOpBehaviour", "NoOpStage"]


class NoOpBehaviour(StrEnum):
    """What the no-op stage should do, so each runner path can be exercised."""

    SUCCEED = "succeed"
    WARN = "warn"
    REJECT = "reject"
    """Refuse on (pretended) scientific grounds. Recorded, never retried."""

    FAIL = "fail"
    """Fail with a non-retryable code."""

    FAIL_RETRYABLE = "fail_retryable"
    """Fail with a retryable code, so the retry path runs."""

    RAISE = "raise"
    """Let an unexpected exception escape, so the catch-all path runs."""

    ORPHAN_THEN_FAIL = "orphan_then_fail"
    """Write a scratch file, then fail. Nothing may become discoverable."""


@dataclass
class NoOpStage:
    """A stage whose only real work is publishing one small JSON artefact."""

    name: str = "noop"
    version: str = "1"
    depends_on: tuple[str, ...] = ()
    parameter_keys: tuple[str, ...] = ("message",)
    algorithm: str | None = "noop"
    algorithm_version: str | None = "1"
    behaviour: NoOpBehaviour = NoOpBehaviour.SUCCEED
    checkpoints: int = 4
    checkpoint_delay_s: float = 0.0
    payload: dict[str, object] = field(default_factory=dict)

    def run(self, context: StageContext) -> StageOutput:
        """Publish a deterministic artefact, or take the requested failure path."""
        for _ in range(max(1, self.checkpoints)):
            context.checkpoint()
            if self.checkpoint_delay_s:
                time.sleep(self.checkpoint_delay_s)

        if self.behaviour is NoOpBehaviour.REJECT:
            raise StageRejected(
                FailureCode.MATCHING_INSUFFICIENT_CANDIDATES,
                f"{self.name}: refusing, as configured, to demonstrate a scientific rejection",
                {"stage": self.name},
            )
        if self.behaviour is NoOpBehaviour.FAIL:
            raise StageFailed(
                FailureCode.PRODUCT_SCHEMA_INVALID,
                f"{self.name}: failing with a non-retryable code, as configured",
                {"stage": self.name},
            )
        if self.behaviour is NoOpBehaviour.FAIL_RETRYABLE:
            raise StageFailed(
                FailureCode.RESOURCE_TIMEOUT,
                f"{self.name}: failing with a retryable code, as configured",
                {"stage": self.name},
            )
        if self.behaviour is NoOpBehaviour.RAISE:
            raise RuntimeError(f"{self.name}: unexpected error, as configured")

        scratch_file = context.scratch_path("result.json")
        scratch_file.write_text(
            json.dumps(
                {
                    "stage": self.name,
                    "version": self.version,
                    "message": context.parameter("message"),
                    "seed": context.seed,
                    "payload": self.payload,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        if self.behaviour is NoOpBehaviour.ORPHAN_THEN_FAIL:
            raise StageFailed(
                FailureCode.PRODUCT_WRITE_FAILED,
                f"{self.name}: failing after writing scratch, as configured. The scratch file "
                "must not become discoverable.",
                {"stage": self.name},
            )

        artifact = context.publish(
            scratch_file,
            kind="noop_result",
            media_type="application/json",
        )
        warnings = (
            (
                StageWarning(
                    code="noop.configured_warning",
                    message="the no-op stage was configured to warn",
                    context={"stage": self.name},
                ),
            )
            if self.behaviour is NoOpBehaviour.WARN
            else ()
        )
        return StageOutput(
            outputs=(artifact,),
            metrics={"artefacts_published": 1},
            warnings=warnings,
        )
