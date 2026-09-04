"""Instantiate verified local model artifacts for inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from selene_core.models.registry import LocalModelRegistry, ModelArtifact, ModelRegistryError

__all__ = ["LoadedModel", "load_local_model"]


@dataclass(frozen=True, slots=True)
class LoadedModel:
    """A verified artifact paired with its in-memory inference object."""

    artifact: ModelArtifact
    value: Any


def load_local_model(
    model_name: str,
    *,
    registry: LocalModelRegistry | None = None,
    version: str | None = None,
    device: str = "cpu",
) -> LoadedModel:
    """Verify and load one active or explicitly versioned local model."""
    selected_registry = registry or LocalModelRegistry.from_environment()
    artifact = selected_registry.resolve(model_name, version=version, verify=True)
    if model_name in {"selene_matcher", "render_residual_prior"}:
        value = _load_torch_model(model_name, artifact, device=device)
    elif model_name == "selene_bias":
        value = _load_joblib_model(artifact)
    elif model_name == "iirs_bandweights":
        value = _load_bandweights(artifact)
    else:
        raise ModelRegistryError(f"no runtime loader exists for model {model_name!r}")
    return LoadedModel(artifact=artifact, value=value)


def _load_torch_model(model_name: str, artifact: ModelArtifact, *, device: str) -> Any:
    if artifact.format != "pytorch_state_dict":
        raise ModelRegistryError(
            f"model {model_name!r} requires pytorch_state_dict, got {artifact.format!r}"
        )
    try:
        import torch

        from selene_core.models.architectures import GroupedDenseMatcher, RenderResidualPrior
    except ImportError as error:
        raise ModelRegistryError("install selene-core[learned] to load PyTorch models") from error
    checkpoint = torch.load(artifact.path, map_location=device, weights_only=True)
    architecture = checkpoint.get("architecture", {})
    if model_name == "selene_matcher":
        model = GroupedDenseMatcher(
            groups=int(architecture.get("groups", 5)),
            feature_channels=int(architecture.get("feature_channels", 32)),
        )
    else:
        model = RenderResidualPrior(angle_channels=int(architecture.get("angle_channels", 3)))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()
    return model


def _load_joblib_model(artifact: ModelArtifact) -> Any:
    if artifact.format != "joblib":
        raise ModelRegistryError(f"selene_bias requires joblib, got {artifact.format!r}")
    try:
        import joblib
    except ImportError as error:
        raise ModelRegistryError("install selene-core[learned] to load bias models") from error
    return joblib.load(artifact.path)


def _load_bandweights(artifact: ModelArtifact) -> dict[str, np.ndarray]:
    if artifact.format != "numpy_npz":
        raise ModelRegistryError(
            f"iirs_bandweights requires numpy_npz, got {artifact.format!r}"
        )
    with np.load(artifact.path, allow_pickle=False) as archive:
        return {name: np.asarray(archive[name]) for name in archive.files}
