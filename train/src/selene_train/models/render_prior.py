"""Small convolutional render-residual prior trainer."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader, TensorDataset

from selene_core.models.architectures import RenderResidualPrior
from selene_train.common import (
    load_array_dataset,
    publish_artifact,
    select_device,
    set_reproducible_seed,
)


def train_render_residual_prior(
    config: dict[str, Any], *, version: str, activate: bool
) -> Path:
    """Train and publish the optional render residual CNN."""
    seed = int(config.get("seed", 20260317))
    set_reproducible_seed(seed)
    dataset_config = config["dataset"]
    arrays = load_array_dataset(
        str(dataset_config["source"]),
        split=str(dataset_config.get("split", "train")),
        fields=("render", "source", "angles", "target_error", "valid_mask"),
    )
    dataset = TensorDataset(
        *(torch.from_numpy(arrays[field]).float() for field in arrays)
    )
    loader = DataLoader(dataset, batch_size=int(config.get("batch_size", 4)), shuffle=True)
    device = torch.device(select_device(str(config.get("device", "auto"))))
    angle_channels = int(arrays["angles"].shape[1])
    model = RenderResidualPrior(angle_channels=angle_channels).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=float(config.get("learning_rate", 1e-3))
    )
    final_loss = 0.0
    for _epoch in range(int(config.get("epochs", 20))):
        total_loss = 0.0
        batches = 0
        for render, source, angles, target_error, valid_mask in loader:
            prediction = model(render.to(device), source.to(device), angles.to(device))
            mask = valid_mask.to(device)
            absolute_error = (prediction - target_error.to(device)).abs() * mask
            loss = absolute_error.sum() / mask.sum().clamp_min(1.0)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            batches += 1
        final_loss = total_loss / max(batches, 1)

    with tempfile.TemporaryDirectory() as temporary_directory:
        checkpoint_path = Path(temporary_directory) / "weights.pt"
        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "architecture": {"angle_channels": angle_channels},
                "seed": seed,
            },
            checkpoint_path,
        )
        return publish_artifact(
            model_root=Path(config.get("model_root", "model")),
            model_name="render_residual_prior",
            version=version,
            artifact_source=checkpoint_path,
            artifact_filename="weights.pt",
            artifact_format="pytorch_state_dict",
            config=config,
            metrics={"train_l1": final_loss},
            metadata={"angle_channels": angle_channels, "device_trained": str(device)},
            activate=activate,
        )
