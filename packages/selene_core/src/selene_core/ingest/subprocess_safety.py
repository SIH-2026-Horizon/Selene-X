"""A hardened invocation helper for ISIS/GDAL/other native command-line tools
(WP-02 task 13).

Every native tool this pipeline shells out to (ISIS's `cam2map`, GDAL's
`gdal_translate`, and similar) is a real operating-system process started
from data this pipeline does not fully control: a caller-supplied product
path, a caller-supplied option value, or simply the ambient environment of
whatever host the pipeline happens to run on. `run_native_tool` is the single
place that invocation happens, so it is the single place these four
properties are enforced, rather than trusting every call site to remember
all of them:

1. **No shell, ever.** `argv` is always a list of literal argument strings
   passed to `subprocess.run(..., shell=False)`; there is no `shell=`
   parameter to flip, and a bare `str` for `argv` (which `subprocess` would
   otherwise happily split into characters or, with `shell=True`, interpret
   as shell syntax) is rejected immediately. This is what turns
   "constructed a shell string by accident" from a silent vulnerability into
   an immediate, loud `TypeError`-family exception.
2. **Caller-derived leading-option rejection.** A caller-supplied value that
   happens to start with `-` can be reinterpreted by the invoked tool as a
   CLI option rather than the plain positional argument it was meant to be
   (the same class of bug `rm -- "$file"` guards against for coreutils).
   `caller_derived_indices` names exactly which `argv` positions came from
   untrusted input; only those positions are checked. A developer-fixed flag
   such as `-v` at a position never named in `caller_derived_indices` is
   completely unaffected — this is a scoped check on specific positions, not
   a blanket ban on `-`-prefixed arguments anywhere in `argv`.
3. **An allow-listed child environment.** `os.environ` is never passed
   through wholesale. The child's environment is built from an explicit
   allow-list of variable names, filtered against whatever is actually set
   in this process's environment, with `env_overrides` applied on top
   (explicit overrides always win over the ambient allow-listed value for
   the same key).
4. **A wall-clock timeout and bounded diagnostic capture.** `subprocess.run`
   is given `timeout=limits.timeout_s`; a `subprocess.TimeoutExpired` is
   caught here and reported through `NativeToolResult.timed_out` rather than
   propagating as an exception, so a caller inspects the outcome instead of
   having to wrap every invocation in its own `try`/`except`. The recorded
   `stdout`/`stderr` are truncated to `limits.max_output_bytes` per stream.

**Scope ruling on "process time/resource limits" (recorded here for
traceability):** this module implements a wall-clock timeout plus bounded
*recorded* diagnostic output. It does **not** attempt OS-level CPU or memory
`rlimit` enforcement via `preexec_fn` — Python's own documentation warns
`preexec_fn` is unsafe to use in a process with multiple threads, and
getting POSIX `resource.setrlimit` semantics exactly right (and only right
on POSIX; there is no equivalent on Windows) is a correctness risk out of
proportion to what this task needs, particularly since no real ISIS/GDAL
binary is invoked anywhere in this environment to actually threaten memory
exhaustion. If a real gap remains here for production use against genuinely
adversarial native tools, it is CPU/memory rlimit enforcement, tracked as a
named follow-up rather than attempted here.

**Honest limitation on "bounded diagnostics":** truncating the *recorded*
`stdout`/`stderr` to `max_output_bytes` bounds what this module keeps and
returns. It does not bound this process's peak memory while
`subprocess.run` itself buffers the child's full output internally before
handing it back — `subprocess.run` reads the child's pipes to completion
(this is what safely avoids the classic full-pipe-buffer deadlock a
hand-rolled `Popen` + manual read loop is easy to get wrong), so a child
that writes gigabytes to stdout before exiting is fully buffered by
`subprocess.run` regardless of `max_output_bytes`. This is a stated,
deliberate scope boundary, not a silent gap: this task's threat model is
diagnostic text (ISIS/GDAL error output is normally small), not defending
against a native tool that adversarially floods its own stdout.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CallerDerivedOptionRejectedError",
    "NativeToolArgumentError",
    "NativeToolLimits",
    "NativeToolResult",
    "run_native_tool",
]


class NativeToolArgumentError(ValueError):
    """`argv` (or a related argument to `run_native_tool`) failed validation
    before any subprocess was started.

    Raised for: a bare `str` passed as `argv`, an empty `argv`, or an `argv`
    containing a non-`str` element. Subclasses `ValueError` so a caller that
    only wants to catch "something about my arguments was wrong" can do so
    generically, while `CallerDerivedOptionRejectedError` remains separately
    catchable for the specific leading-option-rejection case.

    This module deliberately does not carry a `selene_core.pipeline.failures
    .FailureCode` on this exception: every existing code describes a label,
    raster, or stage-level failure, and none genuinely describes "the
    caller constructed an invalid argument list for a subprocess helper" —
    inventing a new member is against this enum's append-only policy absent
    a real, distinct failure identity worth keeping forever. A caller
    translating this into a `StageFailure` is better placed to pick the code
    that fits its own stage's context than this module is to guess one.
    """


class CallerDerivedOptionRejectedError(NativeToolArgumentError):
    """A caller-derived `argv` position started with `-`.

    Only positions named in `caller_derived_indices` are checked; a
    developer-fixed flag at any other position is unaffected. See the
    module docstring, point 2.
    """


# A conservative default: only variables a native tool plausibly needs to
# run at all (locate itself and shared libraries, resolve $HOME-relative
# config, respect the process's locale, find a writable scratch directory).
# Nothing credential-shaped, network-shaped, or Python/interpreter-specific
# is on this list by default — a caller with a genuine, narrower or wider
# need passes `allowed_env_vars` explicitly.
DEFAULT_ALLOWED_ENV_VARS: frozenset[str] = frozenset(
    {
        "PATH",  # required to locate the executable and any tools it shells out to
        "HOME",  # many native tools resolve dotfiles/config relative to this
        "LANG",  # locale: affects number/date formatting in diagnostic output
        "LC_ALL",  # locale override; some tools check this instead of LANG
        "TMPDIR",  # where a tool creates scratch files, if it needs to
    }
)


@dataclass(frozen=True, slots=True)
class NativeToolLimits:
    """Configurable time and output budget for one `run_native_tool` call.

    * ``timeout_s`` (300s / 5 minutes): generous headroom for a real
      ISIS/GDAL invocation on a single scene-sized product, while still
      guaranteeing a hung or runaway process is eventually killed rather
      than blocking a run indefinitely.
    * ``max_output_bytes`` (1 MiB) per stream: ISIS/GDAL diagnostic output
      (warnings, progress text, error messages) is normally small text, not
      the imagery itself — 1 MiB is generous headroom over any legitimate
      diagnostic stream while still bounding what this module records for a
      pathological tool that floods its own stdout/stderr with text.
    """

    timeout_s: float = 300.0
    max_output_bytes: int = 1024 * 1024


@dataclass(frozen=True, slots=True)
class NativeToolResult:
    """The outcome of one `run_native_tool` call.

    Never raised for a non-zero exit code — that is a normal tool outcome
    the caller inspects via `.returncode`, exactly like calling the tool
    directly from a shell would require anyway.

    On ``timed_out=True``: ``returncode`` is `None` (verified against this
    repository's Python 3.12 — `subprocess.TimeoutExpired`, once the child
    is killed, does not expose the killed process's exit status through any
    public attribute, so there is nothing meaningful for this module to put
    there), and ``stdout``/``stderr`` are whatever partial output
    `subprocess.TimeoutExpired` carries (empirically `None` in the common
    case, normalised here to `b""`), each still subject to the configured
    truncation. A caller building a
    `selene_core.pipeline.results.StageFailure` from a timed-out result
    should use `selene_core.pipeline.failures.FailureCode.RESOURCE_TIMEOUT`
    — it exists in the taxonomy for exactly this ("A stage or a subprocess
    exceeded its time limit").
    """

    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


def _validate_argv(argv: Any) -> Sequence[str]:
    """Reject a bare `str` and any other non-`Sequence[str]` shape.

    A bare `str` is checked first and explicitly, ahead of the general
    `Sequence` check, because `str` *is* a `Sequence[str]` structurally
    (iterating it yields one-character strings) — without this explicit
    check first, `run_native_tool("gdalinfo somefile")` would silently pass
    a general sequence check and then be handed to `subprocess.run` as
    `["g", "d", "a", "l", ...]`, which is not a shell-injection risk itself
    but is exactly the "typed a shell-string by accident" mistake this
    module exists to catch loudly instead of letting it misbehave quietly.
    """
    if isinstance(argv, str):
        raise NativeToolArgumentError(
            "argv must be a sequence of str (e.g. a list), not a single str; "
            "a bare command string is exactly the shell-string-construction "
            "mistake this helper exists to catch"
        )
    if not isinstance(argv, Sequence):
        raise NativeToolArgumentError(f"argv must be a Sequence[str], got {type(argv).__name__}")
    if len(argv) == 0:
        raise NativeToolArgumentError("argv must not be empty")
    for i, item in enumerate(argv):
        if not isinstance(item, str):
            raise NativeToolArgumentError(f"argv[{i}] must be str, got {type(item).__name__}")
    return argv


def _reject_caller_derived_leading_options(
    argv: Sequence[str], caller_derived_indices: Sequence[int]
) -> None:
    """Reject a caller-derived `argv` entry that starts with `-`.

    Only the positions named in `caller_derived_indices` are examined. A
    `-`-prefixed value at any other position — a developer-fixed flag like
    `-v`, or an unmarked positional argument — is left alone entirely; see
    the module docstring, point 2, for why a blanket `-`-prefix ban is
    deliberately not what this does.
    """
    for index in caller_derived_indices:
        if not (0 <= index < len(argv)):
            raise NativeToolArgumentError(
                f"caller_derived_indices contains out-of-range index {index} "
                f"for argv of length {len(argv)}"
            )
        if argv[index].startswith("-"):
            raise CallerDerivedOptionRejectedError(
                f"argv[{index}] is caller-derived and starts with '-' "
                f"({argv[index]!r}); this could be interpreted by the invoked "
                "tool as a CLI option rather than a plain positional argument"
            )


def _build_child_env(
    allowed_env_vars: frozenset[str],
    env_overrides: Mapping[str, str] | None,
) -> dict[str, str]:
    """Build the child environment: allow-listed ambient vars, then overrides.

    `os.environ` is filtered down to only the allow-listed keys that are
    actually set in this process, never passed through wholesale.
    `env_overrides`, if given, is applied last so an explicit override always
    wins over the ambient allow-listed value for the same key.
    """
    child_env = {key: value for key, value in os.environ.items() if key in allowed_env_vars}
    if env_overrides:
        child_env.update(env_overrides)
    return child_env


def run_native_tool(
    argv: Sequence[str],
    *,
    caller_derived_indices: Sequence[int] = (),
    limits: NativeToolLimits | None = None,
    env_overrides: Mapping[str, str] | None = None,
    allowed_env_vars: frozenset[str] | None = None,
    cwd: Path | None = None,
) -> NativeToolResult:
    """Invoke a native command-line tool safely and return its outcome.

    `shell=False` is hard-coded and there is no `shell=` parameter on this
    function — see the module docstring for the full set of properties this
    enforces.

    Args:
        argv: The full argument vector, `argv[0]` being the executable.
            Must be a `Sequence[str]` (not a bare `str`) and non-empty.
        caller_derived_indices: Positions in `argv` that came from
            untrusted/caller input, as opposed to fixed, developer-written
            flags. Any named position whose value starts with `-` is
            rejected before `subprocess` is ever invoked.
        limits: Timeout and output-capture budget. Defaults to
            `NativeToolLimits()` when omitted.
        env_overrides: Applied on top of the allow-listed ambient
            environment; wins over an ambient value for the same key.
        allowed_env_vars: Overrides `DEFAULT_ALLOWED_ENV_VARS` for this call.
        cwd: Working directory for the child process, if not the caller's
            own.

    Returns:
        A `NativeToolResult`. Never raised for a non-zero exit code, and
        never raised for a timeout — both are reported through the result's
        fields for the caller to inspect.

    Raises:
        NativeToolArgumentError: `argv` is a bare `str`, is empty, contains
            a non-`str` element, or `caller_derived_indices` names an
            out-of-range position.
        CallerDerivedOptionRejectedError: a caller-derived `argv` position
            starts with `-`.
        FileNotFoundError: the executable named by `argv[0]` does not
            exist. Allowed to propagate directly from `subprocess.run`
            rather than being wrapped — `FileNotFoundError` is already a
            specific, typed, standard-library exception, and wrapping it
            would only hide the real one for no benefit to the caller.
    """
    argv = _validate_argv(argv)
    _reject_caller_derived_leading_options(argv, caller_derived_indices)

    limits = limits if limits is not None else NativeToolLimits()
    resolved_allowed_env_vars = (
        allowed_env_vars if allowed_env_vars is not None else DEFAULT_ALLOWED_ENV_VARS
    )
    child_env = _build_child_env(resolved_allowed_env_vars, env_overrides)

    try:
        # capture_output=True is exactly stdout=PIPE, stderr=PIPE (stdlib
        # sugar for the same pipe-based capture the module docstring
        # describes — subprocess.run still reads both pipes to completion
        # internally, safely avoiding the full-pipe-buffer deadlock a
        # hand-rolled Popen + manual read loop risks).
        completed = subprocess.run(  # noqa: S603 - argv is validated above; shell=False always
            list(argv),
            capture_output=True,
            env=child_env,
            cwd=cwd,
            timeout=limits.timeout_s,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raw_stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        raw_stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        stdout, stdout_truncated = _truncate(raw_stdout, limits.max_output_bytes)
        stderr, stderr_truncated = _truncate(raw_stderr, limits.max_output_bytes)
        return NativeToolResult(
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            timed_out=True,
        )

    stdout, stdout_truncated = _truncate(completed.stdout, limits.max_output_bytes)
    stderr, stderr_truncated = _truncate(completed.stderr, limits.max_output_bytes)
    return NativeToolResult(
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=False,
    )


def _truncate(data: bytes, max_bytes: int) -> tuple[bytes, bool]:
    """Truncate `data` to `max_bytes`, reporting whether truncation occurred."""
    if len(data) > max_bytes:
        return data[:max_bytes], True
    return data, False
