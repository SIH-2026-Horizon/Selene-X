"""PyTorch architectures shared by training and local inference."""

from __future__ import annotations

import torch
from torch import nn

__all__ = ["GroupedDenseMatcher", "RenderResidualPrior"]


class GroupedDenseMatcher(nn.Module):
    """Compact five-group dense flow and uncertainty baseline."""

    def __init__(self, groups: int = 5, feature_channels: int = 32) -> None:
        super().__init__()
        self.groups = groups
        self.stems = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv2d(1, feature_channels, 3, padding=1),
                    nn.GELU(),
                    nn.Conv2d(feature_channels, feature_channels, 3, padding=1),
                )
                for _ in range(groups)
            ]
        )
        self.group_scales = nn.Parameter(torch.ones(groups))
        self.fusion = nn.Sequential(
            nn.Conv2d(feature_channels * 3 + 2, 128, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(128, 128, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(128, 64, 3, padding=1),
            nn.GELU(),
        )
        self.flow_head = nn.Conv2d(64, 2, 3, padding=1)
        self.log_variance_head = nn.Conv2d(64, 1, 3, padding=1)

    def _encode_groups(self, image: torch.Tensor) -> torch.Tensor:
        if image.ndim != 4 or image.shape[1] != self.groups:
            raise ValueError(f"expected [batch, {self.groups}, height, width] input")
        encoded = [
            self.stems[index](image[:, index : index + 1]) * self.group_scales[index]
            for index in range(self.groups)
        ]
        return torch.stack(encoded, dim=0).sum(dim=0)

    def forward(
        self,
        source: torch.Tensor,
        reference: torch.Tensor,
        prior_flow: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        source_features = self._encode_groups(source)
        reference_features = self._encode_groups(reference)
        fused = self.fusion(
            torch.cat(
                [
                    source_features,
                    reference_features,
                    reference_features - source_features,
                    prior_flow,
                ],
                dim=1,
            )
        )
        residual_flow = self.flow_head(fused)
        log_variance = self.log_variance_head(fused).clamp(-8.0, 8.0)
        return prior_flow + residual_flow, log_variance


class RenderResidualPrior(nn.Module):
    """Predict non-negative per-pixel render error."""

    def __init__(self, angle_channels: int = 3) -> None:
        super().__init__()
        input_channels = 2 + angle_channels
        self.network = nn.Sequential(
            nn.Conv2d(input_channels, 32, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(64, 32, 3, padding=1),
            nn.GELU(),
            nn.Conv2d(32, 1, 1),
            nn.Softplus(),
        )

    def forward(
        self, render: torch.Tensor, source: torch.Tensor, angles: torch.Tensor
    ) -> torch.Tensor:
        return self.network(torch.cat([render, source, angles], dim=1))
