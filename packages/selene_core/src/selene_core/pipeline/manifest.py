"""The immutable local run manifest (WP-01 task 7).

The manifest is the self-contained record of one run: what went in, which
parameters were resolved, what each stage did, and what came out. The CLI needs
no database because this file *is* the run's state, and it is rewritten
atomically after every stage so that an interruption leaves the last completed
stage recorded rather than a truncated file.
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field

from selene_core.pipeline.artifacts import atomic_write
from selene_core.pipeline.hashing import digest_json
from selene_core.pipeline.results import (
    EnvironmentFingerprint,
    StageResult,
    _Contract,
)

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "RunManifest",
    "capture_environment",
]

MANIFEST_SCHEMA_VERSION: Final = "1"
"""Bumped when the manifest layout changes incompatibly. A reader that does not
recognise the version refuses the manifest rather than guessing."""

_CODE_REVISION_ENV: Final = "SELENE_CODE_REVISION"

_RECORDED_DEPENDENCIES: Final = ("selene-core", "numpy", "pydantic", "jsonschema")


def capture_environment() -> EnvironmentFingerprint:
    """Describe the interpreter and dependency versions this run used.

    The code revision is read from the ``SELENE_CODE_REVISION`` environment
    variable rather than by shelling out to git. The core package runs no
    subprocesses, and a build that wants its revision recorded can set the
    variable; a checkout that does not simply records ``None``, which is honest.
    """
    versions: dict[str, str] = {}
    for name in _RECORDED_DEPENDENCIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            # An optional dependency that is not installed is simply absent from
            # the fingerprint. Recording a placeholder version would be worse
            # than recording nothing.
            versions[name] = "not installed"
    revision = os.environ.get(_CODE_REVISION_ENV) or None
    return EnvironmentFingerprint(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        code_revision=revision,
        dependency_versions=versions,
    )


class RunManifest(_Contract):
    """Everything needed to understand, verify, and resume one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MANIFEST_SCHEMA_VERSION
    run_id: str
    created_utc: datetime
    updated_utc: datetime

    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="The fully resolved scientific parameter set, including every default. "
        "Hidden defaults are not permitted: a run must record what it actually used.",
    )
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Digest of every external input, keyed by logical name.",
    )
    seed: int | None = None
    environment: EnvironmentFingerprint
    stages: tuple[StageResult, ...] = ()
    limitations: tuple[str, ...] = Field(
        default=(),
        description="Stated limits on what this run's outputs support. Present so that a "
        "result cannot be read as more than it is.",
    )

    @property
    def parameter_digest(self) -> str:
        """Digest of the resolved parameter set."""
        return digest_json(self.parameters)

    def stage(self, name: str) -> StageResult | None:
        """Return the most recent result for ``name``, or ``None``."""
        for result in reversed(self.stages):
            if result.stage_name == name:
                return result
        return None

    def with_stage(self, result: StageResult) -> RunManifest:
        """Return a copy with ``result`` appended and the timestamp advanced.

        Appends rather than replaces: a retried or resumed stage adds an
        attempt, and the earlier attempt stays visible. Run history is
        append-only.
        """
        return self.model_copy(
            update={
                "stages": (*self.stages, result),
                "updated_utc": datetime.now(tz=UTC),
            }
        )

    def write(self, path: Path) -> None:
        """Persist atomically to ``path``."""
        payload = self.model_dump_json(indent=2)
        with atomic_write(path) as temporary:
            temporary.write_text(payload + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> RunManifest:
        """Load a manifest, refusing a layout this build does not understand."""
        manifest = cls.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"run manifest at {path} uses schema version {manifest.schema_version!r}; "
                f"this build understands {MANIFEST_SCHEMA_VERSION!r}"
            )
        return manifest
