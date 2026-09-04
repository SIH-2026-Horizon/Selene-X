"""Resolve versioned model artifacts from a mounted local registry.

The scientific core deliberately performs no network access. Docker and
Kubernetes deployments mount a populated model directory and this module
verifies the selected artifact before an inference adapter loads it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from selene_core.hashing import digest_file, is_sha256

__all__ = ["LocalModelRegistry", "ModelArtifact", "ModelRegistryError"]

_REGISTRY_SCHEMA_VERSION: Final = "1.0.0"
_DEFAULT_MODEL_ROOT: Final = "/models"


class ModelRegistryError(RuntimeError):
    """A model registry entry is missing, unsafe, or fails verification."""


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    """One verified model artifact selected for inference."""

    model_name: str
    version: str
    format: str
    path: Path
    sha256: str
    metadata: dict[str, Any]


class LocalModelRegistry:
    """Read model versions from ``registry.json`` under a mounted root."""

    REGISTRY_FILENAME: Final = "registry.json"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    @classmethod
    def from_environment(cls) -> LocalModelRegistry:
        """Use ``SXR_MODEL_ROOT`` or the container default ``/models``."""
        return cls(Path(os.environ.get("SXR_MODEL_ROOT", _DEFAULT_MODEL_ROOT)))

    @property
    def registry_path(self) -> Path:
        return self.root / self.REGISTRY_FILENAME

    def resolve(
        self,
        model_name: str,
        *,
        version: str | None = None,
        verify: bool = True,
    ) -> ModelArtifact:
        """Resolve an active or explicitly versioned artifact.

        Args:
            model_name: Registry model key, such as ``selene_matcher``.
            version: Explicit version. When omitted, use ``active_version``.
            verify: Recompute and compare the artifact SHA-256.
        """
        document = self._load_registry()
        models = document.get("models")
        if not isinstance(models, dict):
            raise ModelRegistryError("registry models must be an object")
        model = models.get(model_name)
        if not isinstance(model, dict):
            raise ModelRegistryError(f"model {model_name!r} is absent from the registry")

        selected_version = version or model.get("active_version")
        if not isinstance(selected_version, str) or not selected_version:
            raise ModelRegistryError(f"model {model_name!r} has no active version")
        versions = model.get("versions")
        if not isinstance(versions, dict):
            raise ModelRegistryError(f"model {model_name!r} versions must be an object")
        entry = versions.get(selected_version)
        if not isinstance(entry, dict):
            raise ModelRegistryError(
                f"model {model_name!r} version {selected_version!r} is absent"
            )

        relative_path = entry.get("path")
        artifact_format = entry.get("format")
        expected_digest = entry.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            raise ModelRegistryError("model artifact path must be a non-empty string")
        if not isinstance(artifact_format, str) or not artifact_format:
            raise ModelRegistryError("model artifact format must be a non-empty string")
        if not isinstance(expected_digest, str) or not is_sha256(expected_digest):
            raise ModelRegistryError("model artifact sha256 must be lowercase SHA-256")

        artifact_path = (self.root / relative_path).resolve()
        if not artifact_path.is_relative_to(self.root):
            raise ModelRegistryError("model artifact path escapes SXR_MODEL_ROOT")
        if not artifact_path.is_file():
            raise ModelRegistryError(f"model artifact does not exist: {artifact_path}")
        if verify:
            actual_digest = digest_file(artifact_path)
            if actual_digest != expected_digest:
                raise ModelRegistryError(
                    f"model artifact checksum mismatch: expected {expected_digest}, "
                    f"got {actual_digest}"
                )

        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ModelRegistryError("model artifact metadata must be an object")
        return ModelArtifact(
            model_name=model_name,
            version=selected_version,
            format=artifact_format,
            path=artifact_path,
            sha256=expected_digest,
            metadata=dict(metadata),
        )

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            raise ModelRegistryError(f"model registry does not exist: {self.registry_path}")
        try:
            document = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ModelRegistryError(f"cannot read model registry: {error}") from error
        if not isinstance(document, dict):
            raise ModelRegistryError("model registry root must be an object")
        if document.get("schema_version") != _REGISTRY_SCHEMA_VERSION:
            raise ModelRegistryError(
                f"model registry schema_version must be {_REGISTRY_SCHEMA_VERSION!r}"
            )
        return document
