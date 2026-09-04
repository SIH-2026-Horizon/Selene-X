"""Skeleton packaging checks.

These do not test any scientific behaviour, because none exists yet. They prove
that the workspace layout from section 5.2 of the implementation plan is
installable, importable, and typed.
"""

import importlib
import pathlib

import pytest

DISTRIBUTIONS = ["selene_core", "selene_client", "selene_service", "selene_worker"]

CORE_SUBPACKAGES = [
    "ingest",
    "geometry",
    "reference",
    "preprocess",
    "features",
    "match",
    "select",
    "refine",
    "adjust",
    "metrics",
    "products",
    "pipeline",
]


@pytest.mark.unit
@pytest.mark.parametrize("name", DISTRIBUTIONS)
def test_package_imports_and_declares_a_version(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__version__


@pytest.mark.unit
@pytest.mark.parametrize("name", DISTRIBUTIONS)
def test_package_ships_a_py_typed_marker(name: str) -> None:
    module = importlib.import_module(name)
    root = pathlib.Path(next(iter(module.__path__)))
    assert (root / "py.typed").is_file()


@pytest.mark.unit
@pytest.mark.parametrize("name", CORE_SUBPACKAGES)
def test_core_stage_subpackage_exists(name: str) -> None:
    assert importlib.import_module(f"selene_core.{name}")


@pytest.mark.unit
def test_core_has_no_infrastructure_dependency_at_import_time() -> None:
    """ADR-005 as a runtime check.

    ``lint-imports`` enforces this statically in CI. This asserts the weaker but
    independent property that importing the core does not drag a service
    dependency into the interpreter.
    """
    import subprocess
    import sys

    forbidden = ["fastapi", "sqlalchemy", "uvicorn", "starlette"]
    probe = (
        "import sys, selene_core;"
        f"loaded=[m for m in {forbidden!r} if m in sys.modules];"
        "print(','.join(loaded))"
    )
    result = subprocess.run(  # noqa: S603 - fixed argument array, no shell
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


@pytest.mark.unit
def test_service_and_worker_are_limited_to_the_core_public_facade() -> None:
    """ADR-0005's public-facade rule is executable, not documentation only."""
    import subprocess
    import sys

    config = pathlib.Path(".importlinter").read_text(encoding="utf-8")
    assert "[importlinter:contract:service-and-worker-use-core-public-api]" in config
    assert "selene_core.**" in config

    result = subprocess.run(  # noqa: S603 - executable is the active virtualenv's lint-imports entry point
        [str(pathlib.Path(sys.executable).with_name("lint-imports"))],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "only import selene_core's documented public API" in result.stdout
    assert "Contracts: 6 kept, 0 broken." in result.stdout
