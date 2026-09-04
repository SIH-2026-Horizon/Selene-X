"""Shared dataset, reproducibility, and artifact publishing helpers."""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

MODEL_NAMES = (
    "selene_matcher",
    "selene_bias",
    "iirs_bandweights",
    "render_residual_prior",
)


def load_config(path: Path) -> dict[str, Any]:
    """Load one JSON training configuration."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("training config root must be an object")
    model_name = document.get("model_name")
    if model_name not in MODEL_NAMES:
        raise ValueError(f"unsupported model_name: {model_name!r}")
    return document


def set_reproducible_seed(seed: int) -> None:
    """Seed Python, NumPy, and PyTorch when available."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def select_device(requested: str) -> str:
    """Resolve ``auto`` to CUDA when available, otherwise CPU."""
    if requested != "auto":
        return requested
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def load_array_dataset(
    source: str,
    *,
    split: str,
    fields: Sequence[str],
) -> dict[str, np.ndarray]:
    """Load named arrays from local NPZ data or a Hugging Face dataset."""
    resolved_source = os.environ.get("SXR_DATASET_REPO", source)
    if resolved_source.startswith("hf://"):
        return _load_hugging_face_arrays(resolved_source[5:], split=split, fields=fields)

    dataset_path = Path(resolved_source)
    if dataset_path.is_dir():
        dataset_path = dataset_path / f"{split}.npz"
    if not dataset_path.is_file():
        raise FileNotFoundError(f"dataset split does not exist: {dataset_path}")
    with np.load(dataset_path, allow_pickle=False) as archive:
        missing = [field for field in fields if field not in archive]
        if missing:
            raise ValueError(f"dataset is missing fields: {', '.join(missing)}")
        return {field: np.asarray(archive[field]) for field in fields}


def _load_hugging_face_arrays(
    repository_id: str,
    *,
    split: str,
    fields: Sequence[str],
) -> dict[str, np.ndarray]:
    try:
        from datasets import load_dataset
    except ImportError as error:
        raise RuntimeError("install the training dependencies to use Hugging Face data") from error

    dataset = load_dataset(repository_id, split=split, token=os.environ.get("HF_TOKEN"))
    missing = [field for field in fields if field not in dataset.column_names]
    if missing:
        raise ValueError(f"Hugging Face dataset is missing fields: {', '.join(missing)}")
    return {
        field: np.stack([np.asarray(value) for value in dataset[field]], axis=0)
        for field in fields
    }


def publish_artifact(
    *,
    model_root: Path,
    model_name: str,
    version: str,
    artifact_source: Path,
    artifact_filename: str,
    artifact_format: str,
    config: Mapping[str, Any],
    metrics: Mapping[str, float],
    metadata: Mapping[str, Any],
    activate: bool,
) -> Path:
    """Publish an artifact and atomically update the local registry."""
    if model_name not in MODEL_NAMES:
        raise ValueError(f"unsupported model_name: {model_name!r}")
    output_directory = model_root / model_name / version
    output_directory.mkdir(parents=True, exist_ok=True)
    artifact_path = output_directory / artifact_filename
    artifact_path.write_bytes(artifact_source.read_bytes())
    digest = _digest_file(artifact_path)

    run_document = {
        "schema_version": "1.0.0",
        "model_name": model_name,
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "artifact": {
            "path": artifact_filename,
            "format": artifact_format,
            "sha256": digest,
        },
        "config": dict(config),
        "metrics": dict(metrics),
        "metadata": dict(metadata),
    }
    _atomic_json_write(output_directory / "manifest.json", run_document)
    _update_registry(
        model_root=model_root,
        model_name=model_name,
        version=version,
        relative_path=artifact_path.relative_to(model_root).as_posix(),
        artifact_format=artifact_format,
        digest=digest,
        metadata=metadata,
        activate=activate,
    )
    return artifact_path


def _update_registry(
    *,
    model_root: Path,
    model_name: str,
    version: str,
    relative_path: str,
    artifact_format: str,
    digest: str,
    metadata: Mapping[str, Any],
    activate: bool,
) -> None:
    registry_path = model_root / "registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {"schema_version": "1.0.0", "models": {}}
    if registry.get("schema_version") != "1.0.0" or not isinstance(
        registry.get("models"), dict
    ):
        raise ValueError("existing model registry is not schema version 1.0.0")

    models = registry["models"]
    model_entry = models.setdefault(model_name, {"active_version": None, "versions": {}})
    versions = model_entry.setdefault("versions", {})
    versions[version] = {
        "path": relative_path,
        "format": artifact_format,
        "sha256": digest,
        "metadata": dict(metadata),
    }
    if activate or not model_entry.get("active_version"):
        model_entry["active_version"] = version
    _atomic_json_write(registry_path, registry)


def _atomic_json_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
