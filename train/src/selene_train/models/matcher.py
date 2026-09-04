"""Grouped dense-flow matcher and supervised training loop."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from selene_core.models.architectures import GroupedDenseMatcher
from selene_train.common import (
    load_array_dataset,
    publish_artifact,
    select_device,
    set_reproducible_seed,
)


def train_selene_matcher(config: dict[str, Any], *, version: str, activate: bool) -> Path:
    """Train and publish the five-group dense matcher."""
    seed = int(config.get("seed", 20260317))
    set_reproducible_seed(seed)
    dataset_config = config["dataset"]
    arrays = load_array_dataset(
        str(dataset_config["source"]),
        split=str(dataset_config.get("split", "train")),
        fields=("source", "reference", "prior_flow", "flow", "valid_mask"),
    )
    dataset = TensorDataset(
        *(torch.from_numpy(arrays[field]).float() for field in arrays)
    )
    batch_size = int(config.get("batch_size", 2))
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
    device = torch.device(select_device(str(config.get("device", "auto"))))
    model = GroupedDenseMatcher(
        groups=int(config.get("groups", 5)),
        feature_channels=int(config.get("feature_channels", 32)),
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config.get("learning_rate", 2e-4)),
        weight_decay=float(config.get("weight_decay", 0.01)),
    )
    epochs = int(config.get("epochs", 20))
    final_loss = 0.0
    model.train()
    for _epoch in range(epochs):
        total_loss = 0.0
        batches = 0
        for source, reference, prior_flow, target_flow, valid_mask in loader:
            source = source.to(device)
            reference = reference.to(device)
            prior_flow = prior_flow.to(device)
            target_flow = target_flow.to(device)
            valid_mask = valid_mask.to(device)
            predicted_flow, log_variance = model(source, reference, prior_flow)
            endpoint_error = torch.linalg.vector_norm(
                predicted_flow - target_flow, dim=1, keepdim=True
            )
            masked_error = endpoint_error * valid_mask
            denominator = valid_mask.sum().clamp_min(1.0)
            l1_loss = masked_error.sum() / denominator
            gaussian_nll = (
                0.5 * (torch.exp(-log_variance) * endpoint_error.square() + log_variance)
                * valid_mask
            ).sum() / denominator
            loss = l1_loss + float(config.get("confidence_loss_weight", 0.2)) * gaussian_nll
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(config.get("gradient_clip", 1.0)))
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            batches += 1
        final_loss = total_loss / max(batches, 1)

    model.eval()
    with tempfile.TemporaryDirectory() as temporary_directory:
        checkpoint_path = Path(temporary_directory) / "weights.pt"
        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "architecture": {
                    "groups": model.groups,
                    "feature_channels": int(config.get("feature_channels", 32)),
                },
                "seed": seed,
            },
            checkpoint_path,
        )
        return publish_artifact(
            model_root=Path(config.get("model_root", "model")),
            model_name="selene_matcher",
            version=version,
            artifact_source=checkpoint_path,
            artifact_filename="weights.pt",
            artifact_format="pytorch_state_dict",
            config=config,
            metrics={"train_loss": final_loss},
            metadata={"groups": model.groups, "device_trained": str(device)},
            activate=activate,
        )
