"""Gradient-boosted sub-pixel estimator bias training."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from selene_train.common import load_array_dataset, publish_artifact, set_reproducible_seed


def train_selene_bias(config: dict[str, Any], *, version: str, activate: bool) -> Path:
    """Train and publish the sub-pixel bias regressor."""
    seed = int(config.get("seed", 20260317))
    set_reproducible_seed(seed)
    dataset_config = config["dataset"]
    arrays = load_array_dataset(
        str(dataset_config["source"]),
        split=str(dataset_config.get("split", "train")),
        fields=("features", "target_bias"),
    )
    features = np.asarray(arrays["features"], dtype=np.float32)
    target_bias = np.asarray(arrays["target_bias"], dtype=np.float32)
    if target_bias.ndim == 1:
        target_bias = target_bias[:, None]
    models = []
    predictions = np.empty_like(target_bias)
    for component_index in range(target_bias.shape[1]):
        regressor = HistGradientBoostingRegressor(
            learning_rate=float(config.get("learning_rate", 0.05)),
            max_iter=int(config.get("max_iter", 300)),
            max_leaf_nodes=int(config.get("max_leaf_nodes", 31)),
            l2_regularization=float(config.get("l2_regularization", 1e-3)),
            random_state=seed,
        )
        regressor.fit(features, target_bias[:, component_index])
        predictions[:, component_index] = regressor.predict(features)
        models.append(regressor)
    train_mae = float(mean_absolute_error(target_bias, predictions))

    with tempfile.TemporaryDirectory() as temporary_directory:
        artifact_path = Path(temporary_directory) / "bias_model.pkl"
        joblib.dump(
            {
                "models": models,
                "feature_names": config.get("feature_names", []),
                "target_components": int(target_bias.shape[1]),
                "seed": seed,
            },
            artifact_path,
        )
        return publish_artifact(
            model_root=Path(config.get("model_root", "model")),
            model_name="selene_bias",
            version=version,
            artifact_source=artifact_path,
            artifact_filename="bias_model.pkl",
            artifact_format="joblib",
            config=config,
            metrics={"train_mae_px": train_mae},
            metadata={
                "feature_count": int(features.shape[1]),
                "target_components": int(target_bias.shape[1]),
            },
            activate=activate,
        )
