"""Small, service-only execution lifecycle policy.

This validates orchestration state, not science.  In particular, changing an
execution state must never assign or alter a computed scientific verdict.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    """Durable lifecycle values used by the initial service foundation."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvalidExecutionTransition(ValueError):
    """Raised when a lifecycle transition is absent from the documented graph."""


_ALLOWED_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset({ExecutionState.QUEUED, ExecutionState.CANCELLED}),
    ExecutionState.QUEUED: frozenset(
        {ExecutionState.RUNNING, ExecutionState.CANCELLING, ExecutionState.CANCELLED}
    ),
    ExecutionState.RUNNING: frozenset(
        {
            ExecutionState.SUCCEEDED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLING,
        }
    ),
    ExecutionState.CANCELLING: frozenset({ExecutionState.CANCELLED, ExecutionState.FAILED}),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.SUCCEEDED: frozenset(),
    ExecutionState.FAILED: frozenset(),
}


def allowed_execution_transitions(state: ExecutionState) -> frozenset[ExecutionState]:
    """Return the terminal-aware outgoing transitions for *state*."""

    return _ALLOWED_TRANSITIONS[state]


def validate_execution_transition(current: ExecutionState, target: ExecutionState) -> None:
    """Ensure that the documented run lifecycle permits ``current -> target``."""

    if target not in allowed_execution_transitions(current):
        raise InvalidExecutionTransition(
            f"execution transition {current!s} -> {target!s} is not allowed"
        )
