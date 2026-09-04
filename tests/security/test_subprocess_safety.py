"""Tests for the secure native-tool invocation helper (WP-02 task 13).

Every command invoked below is a safe, always-present binary
(`python3 -c "..."`) — never a real ISIS/GDAL binary, none of which exist in
this environment. No `sh -c`/shell invocation is used anywhere, consistent
with `run_native_tool` hard-coding `shell=False`.
"""

from __future__ import annotations

import ast
import sys
import time

import pytest

from selene_core.ingest.subprocess_safety import (
    CallerDerivedOptionRejectedError,
    NativeToolArgumentError,
    NativeToolLimits,
    run_native_tool,
)

pytestmark = pytest.mark.security

_PYTHON = sys.executable


# --------------------------------------------------------------------------
# argv type/shape validation
# --------------------------------------------------------------------------


def test_bare_str_argv_is_rejected() -> None:
    """A bare `str` for `argv` is rejected before any subprocess call.

    This is the "typed a shell string by accident" mistake the module
    exists to catch loudly (see module docstring).
    """
    with pytest.raises(NativeToolArgumentError):
        # str satisfies Sequence[str] structurally at the type level (it is
        # a sequence of one-character strings) — the runtime check in
        # run_native_tool is exactly what catches this at the value level.
        run_native_tool(f"{_PYTHON} -c 'print(1)'")


def test_empty_argv_is_rejected() -> None:
    with pytest.raises(NativeToolArgumentError):
        run_native_tool([])


# --------------------------------------------------------------------------
# Caller-derived leading-option rejection: scoped, not blanket
# --------------------------------------------------------------------------


def test_caller_derived_leading_option_is_rejected() -> None:
    """A `-`-prefixed value at a *marked* caller-derived position is rejected
    before any subprocess call."""
    argv = [_PYTHON, "-c", "import sys; print(len(sys.argv))", "-x"]

    with pytest.raises(CallerDerivedOptionRejectedError):
        run_native_tool(argv, caller_derived_indices=(3,))


def test_same_leading_dash_value_at_unmarked_position_is_not_rejected() -> None:
    """The identical `-x` value used above, at the identical position, is
    NOT rejected when that position is not named in `caller_derived_indices`
    — proving the rejection is scoped to marked positions, not a blanket
    `-`-prefix ban. The developer-fixed `-c` flag at index 1 (never marked)
    working normally is further, structural proof of the same point.
    """
    argv = [_PYTHON, "-c", "import sys; print(len(sys.argv))", "-x"]

    result = run_native_tool(argv, caller_derived_indices=())

    assert result.timed_out is False
    assert result.returncode == 0
    # sys.argv for `python3 -c CODE -x` is ["-c", "-x"] (argv[0] is "-c",
    # not the interpreter path) — length 2, not the full 4-element argv.
    assert result.stdout.strip() == b"2"


# --------------------------------------------------------------------------
# Environment allow-listing
# --------------------------------------------------------------------------


def test_non_allowlisted_env_var_is_absent_from_child_but_path_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SELENE_TEST_NOT_ALLOWLISTED", "secret-value")

    argv = [
        _PYTHON,
        "-c",
        "import os, sys; sys.stdout.write(repr(dict(os.environ)))",
    ]
    result = run_native_tool(argv)

    assert result.timed_out is False
    assert result.returncode == 0
    child_env = ast.literal_eval(result.stdout.decode("utf-8"))
    assert "SELENE_TEST_NOT_ALLOWLISTED" not in child_env
    assert "PATH" in child_env


def test_env_overrides_win_over_ambient_allowlisted_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANG", "ambient-value")

    argv = [
        _PYTHON,
        "-c",
        "import os, sys; sys.stdout.write(os.environ.get('LANG', ''))",
    ]
    result = run_native_tool(argv, env_overrides={"LANG": "overridden-value"})

    assert result.timed_out is False
    assert result.stdout == b"overridden-value"


# --------------------------------------------------------------------------
# Timeout
# --------------------------------------------------------------------------


def test_timeout_fires_promptly_and_reports_timed_out() -> None:
    argv = [_PYTHON, "-c", "import time; time.sleep(5)"]

    started = time.monotonic()
    result = run_native_tool(argv, limits=NativeToolLimits(timeout_s=0.2))
    elapsed = time.monotonic() - started

    # Proves the timeout actually fired (subprocess.run's own timeout
    # mechanism killed the child) rather than the test simply waiting out
    # the full 5-second sleep: 5s would blow well past this bound.
    assert elapsed < 3.0
    assert result.timed_out is True
    assert result.returncode is None


# --------------------------------------------------------------------------
# Bounded diagnostics
# --------------------------------------------------------------------------


def test_stdout_over_cap_is_truncated_to_exact_boundary() -> None:
    argv = [_PYTHON, "-c", "import sys; sys.stdout.write('x' * 100000)"]

    result = run_native_tool(argv, limits=NativeToolLimits(max_output_bytes=100))

    assert result.stdout_truncated is True
    assert len(result.stdout) == 100
    assert result.stdout == b"x" * 100


def test_stdout_under_cap_is_not_truncated() -> None:
    argv = [_PYTHON, "-c", "import sys; sys.stdout.write('hello')"]

    result = run_native_tool(argv, limits=NativeToolLimits(max_output_bytes=100))

    assert result.stdout_truncated is False
    assert result.stdout == b"hello"


# --------------------------------------------------------------------------
# Non-zero exit / missing executable
# --------------------------------------------------------------------------


def test_non_zero_exit_code_does_not_raise() -> None:
    argv = [_PYTHON, "-c", "import sys; sys.exit(3)"]

    result = run_native_tool(argv)

    assert result.timed_out is False
    assert result.returncode == 3


def test_nonexistent_executable_raises_file_not_found_error() -> None:
    with pytest.raises(FileNotFoundError):
        run_native_tool(["/selene-xr-nonexistent-binary-for-tests"])
