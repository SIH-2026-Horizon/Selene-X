"""Learned IIRS spectral-collapse weights."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.nn import functional as functional

from selene_train.common import (
    load_array_dataset,
    publish_artifact,
    select_device,
    set_reproducible_seed,
)


def _gradient_magnitude(images: torch.Tensor) -> torch.Tensor:
    horizontal = images[..., :, 1:] - images[..., :, :-1]
    vertical = images[..., 1:, :] - images[..., :-1, :]
    horizontal = functional.pad(horizontal, (0, 1, 0, 0))
    vertical = functional.pad(vertical, (0, 0, 0, 1))
    return torch.sqrt(horizontal.square() + vertical.square() + 1e-8)


def train_iirs_bandweights(config: dict[str, Any], *, version: str, activate: bool) -> Path:
    """Fit a sum-normalized IIRS band vector against structural target contrast."""
    seed = int(config.get("seed", 20260317))
    set_reproducible_seed(seed)
    dataset_config = config["dataset"]
    arrays = load_array_dataset(
        str(dataset_config["source"]),
        split=str(dataset_config.get("split", "train")),
        fields=("radiance", "target", "valid_mask"),
    )
    device = torch.device(select_device(str(config.get("device", "auto"))))
    radiance = torch.from_numpy(arrays["radiance"]).float().to(device)
    target = torch.from_numpy(arrays["target"]).float().to(device)
    mask = torch.from_numpy(arrays["valid_mask"]).float().to(device)
    band_count = int(radiance.shape[1])
    logits = torch.zeros(band_count, device=device, requires_grad=True)
    optimizer = torch.optim.Adam([logits], lr=float(config.get("learning_rate", 0.05)))
    target_gradient = _gradient_magnitude(target)
    final_loss = 0.0
    for _step in range(int(config.get("steps", 2000))):
        weights = torch.softmax(logits, dim=0)
        proxy = (radiance * weights.view(1, -1, 1, 1)).sum(dim=1, keepdim=True)
        proxy_gradient = _gradient_magnitude(proxy)
        valid_count = mask.sum().clamp_min(1.0)
        proxy_mean = (proxy_gradient * mask).sum() / valid_count
        target_mean = (target_gradient * mask).sum() / valid_count
        proxy_centered = (proxy_gradient - proxy_mean) * mask
        target_centered = (target_gradient - target_mean) * mask
        correlation = (proxy_centered * target_centered).sum() / (
            torch.sqrt(proxy_centered.square().sum() * target_centered.square().sum()) + 1e-8
        )
        loss = -correlation
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().cpu())

    learned_weights = torch.softmax(logits.detach(), dim=0).cpu().numpy().astype(np.float32)
    with tempfile.TemporaryDirectory() as temporary_directory:
        artifact_path = Path(temporary_directory) / "bandweights.npz"
        np.savez(
            artifact_path,
            weights=learned_weights,
            target_instrument=np.asarray(str(config.get("target_instrument", "TMC2"))),
        )
        return publish_artifact(
            model_root=Path(config.get("model_root", "model")),
            model_name="iirs_bandweights",
            version=version,
            artifact_source=artifact_path,
            artifact_filename="bandweights.npz",
            artifact_format="numpy_npz",
            config=config,
            metrics={"negative_gradient_correlation": final_loss},
            metadata={
                "band_count": band_count,
                "target_instrument": str(config.get("target_instrument", "TMC2")),
            },
            activate=activate,
        )
