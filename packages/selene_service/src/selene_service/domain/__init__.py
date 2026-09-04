"""Domain services orchestrating ``selene_core`` on behalf of the API (WP-10).

Execution state, computed scientific verdict, and human disposition are kept as
separate fields. An execution failure never receives a fabricated scientific
verdict. Review and override records append to history and never alter a
computed verdict.
"""

from selene_service.domain.execution import (
    ExecutionState,
    InvalidExecutionTransition,
    allowed_execution_transitions,
    validate_execution_transition,
)

__all__ = [
    "ExecutionState",
    "InvalidExecutionTransition",
    "allowed_execution_transitions",
    "validate_execution_transition",
]
