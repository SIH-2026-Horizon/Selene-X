"""Tests for mounted local model artifact resolution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from selene_core.models import LocalModelRegistry, ModelRegistryError, load_local_model


def _write_registry(root: Path, *, relative_path: str, digest: str) -> None:
    document = {
        "schema_version": "1.0.0",
        "models": {
            "selene_matcher": {
                "active_version": "dev",
                "versions": {
                    "dev": {
                        "path": relative_path,
                        "format": "pytorch_state_dict",
                        "sha256": digest,
                        "metadata": {"channels": 5},
                    }
                },
            }
        },
    }
    (root / "registry.json").write_text(json.dumps(document), encoding="utf-8")


def test_registry_resolves_and_verifies_active_model(tmp_path: Path) -> None:
    artifact = tmp_path / "selene_matcher" / "dev" / "weights.pt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"weights")
    digest = hashlib.sha256(b"weights").hexdigest()
    _write_registry(tmp_path, relative_path="selene_matcher/dev/weights.pt", digest=digest)

    resolved = LocalModelRegistry(tmp_path).resolve("selene_matcher")

    assert resolved.path == artifact
    assert resolved.version == "dev"
    assert resolved.metadata == {"channels": 5}


def test_registry_rejects_checksum_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "selene_matcher" / "dev" / "weights.pt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"changed")
    _write_registry(tmp_path, relative_path="selene_matcher/dev/weights.pt", digest="a" * 64)

    with pytest.raises(ModelRegistryError, match="checksum mismatch"):
        LocalModelRegistry(tmp_path).resolve("selene_matcher")


def test_registry_rejects_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.pt"
    outside.write_bytes(b"weights")
    digest = hashlib.sha256(b"weights").hexdigest()
    _write_registry(tmp_path, relative_path="../outside.pt", digest=digest)

    with pytest.raises(ModelRegistryError, match="escapes"):
        LocalModelRegistry(tmp_path).resolve("selene_matcher")


def test_runtime_loads_bandweights(tmp_path: Path) -> None:
    artifact = tmp_path / "iirs_bandweights" / "dev" / "bandweights.npz"
    artifact.parent.mkdir(parents=True)
    np.savez(artifact, weights=np.asarray([0.25, 0.75], dtype=np.float32))
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    document = {
        "schema_version": "1.0.0",
        "models": {
            "iirs_bandweights": {
                "active_version": "dev",
                "versions": {
                    "dev": {
                        "path": "iirs_bandweights/dev/bandweights.npz",
                        "format": "numpy_npz",
                        "sha256": digest,
                        "metadata": {"band_count": 2},
                    }
                },
            }
        },
    }
    (tmp_path / "registry.json").write_text(json.dumps(document), encoding="utf-8")

    loaded = load_local_model("iirs_bandweights", registry=LocalModelRegistry(tmp_path))

    np.testing.assert_allclose(loaded.value["weights"], [0.25, 0.75])
