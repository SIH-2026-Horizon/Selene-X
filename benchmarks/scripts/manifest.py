"""Benchmark manifest loader and validator (WP-00 task 1).

A benchmark manifest records which products a benchmark run depends on: their
identifiers, source URLs, licences, per-file checksums, split roles, stress
bins, and control uncertainty. This module only loads and validates the JSON
document against ``schemas/benchmark-manifest.schema.json``; it does not
touch the filesystem for the referenced product files (see
``acquisition_check`` for that).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from benchmarks.scripts.leakage_check import SplitIntegrityError, validate_split_integrity

__all__ = [
    "SCHEMA_PATH",
    "ManifestValidationError",
    "SplitIntegrityError",
    "load_manifest",
    "load_schema",
]

SCHEMA_PATH: Final = (
    Path(__file__).resolve().parents[2] / "schemas" / "benchmark-manifest.schema.json"
)


class ManifestValidationError(ValueError):
    """Raised when a manifest document fails schema validation.

    Carries the underlying :class:`jsonschema.exceptions.ValidationError`'s
    ``message`` and ``json_path`` so a caller can identify exactly which field
    or rule failed, rather than a bare "invalid manifest".
    """

    def __init__(self, path: Path, error: jsonschema.exceptions.ValidationError) -> None:
        self.manifest_path = path
        self.json_path = error.json_path
        self.validator_message = error.message
        super().__init__(f"{path} failed schema validation at {error.json_path}: {error.message}")


def load_schema() -> dict[str, Any]:
    """Load and return the benchmark manifest JSON Schema document."""
    document: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return document


def load_manifest(path: Path) -> dict[str, Any]:
    """Read, parse, and schema-validate a benchmark manifest file.

    Args:
        path: Path to a manifest JSON document.

    Returns:
        The parsed manifest as a dict, once it has been confirmed schema-valid.

    Raises:
        ManifestValidationError: If the document does not conform to
            ``schemas/benchmark-manifest.schema.json``. The underlying
            ``jsonschema`` error's message and JSON path are preserved.
        json.JSONDecodeError: If the file is not valid JSON.
        OSError: If the file cannot be read.
    """
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    schema = load_schema()
    try:
        jsonschema.validate(document, schema)
    except jsonschema.exceptions.ValidationError as error:
        raise ManifestValidationError(path, error) from error
    validate_split_integrity(document)
    return document
