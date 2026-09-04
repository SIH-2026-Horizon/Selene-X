"""Command-line interface for all SELENE-XR trainers."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from selene_train.common import MODEL_NAMES, load_config
from selene_train.models import (
    train_iirs_bandweights,
    train_render_residual_prior,
    train_selene_bias,
    train_selene_matcher,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train SELENE-XR model artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    train_parser = subparsers.add_parser("train", help="run one model training pipeline")
    train_parser.add_argument("--config", type=Path, required=True)
    train_parser.add_argument("--version", required=True)
    train_parser.add_argument("--dataset", help="override dataset source or hf:// repository")
    train_parser.add_argument("--model-root", type=Path, help="override artifact registry root")
    train_parser.add_argument("--no-activate", action="store_true")
    subparsers.add_parser("list-models", help="show supported model names")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the training CLI."""
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "list-models":
        for model_name in MODEL_NAMES:
            print(model_name)
        return 0

    config = load_config(arguments.config)
    if arguments.dataset:
        config.setdefault("dataset", {})["source"] = arguments.dataset
    if arguments.model_root:
        config["model_root"] = str(arguments.model_root)
    trainers: dict[str, Callable[..., Path]] = {
        "selene_matcher": train_selene_matcher,
        "selene_bias": train_selene_bias,
        "iirs_bandweights": train_iirs_bandweights,
        "render_residual_prior": train_render_residual_prior,
    }
    artifact_path = trainers[config["model_name"]](
        config,
        version=arguments.version,
        activate=not arguments.no_activate,
    )
    print(artifact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
