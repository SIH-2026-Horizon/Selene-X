"""Focused transactional persistence helpers for initial run lifecycle writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from selene_service.domain.execution import ExecutionState, validate_execution_transition
from selene_service.persistence.models import Review, Run, RunEvent
from selene_service.persistence.validation import validate_sha256


class SessionWriter(Protocol):
    """The deliberately small session seam needed by lifecycle persistence."""

    def add(self, instance: object) -> None:
        """Stage an ORM instance in a caller-owned unit of work."""


class ConcurrentRunTransitionError(RuntimeError):
    """Raised when a stale run snapshot loses the optimistic transition race."""


class ReservedEventDocumentFieldError(ValueError):
    """Raised when caller metadata tries to override authoritative event facts."""


class ConcurrentReviewSubmissionError(RuntimeError):
    """Raised when an intervening run event invalidates a review submission."""


_RESERVED_EVENT_DOCUMENT_FIELDS = frozenset(
    {
        "actor_subject_id",
        "event_type",
        "execution_state",
        "from_execution_state",
        "run_id",
        "sequence",
        "state_version",
        "to_execution_state",
    }
)


@dataclass(frozen=True, slots=True)
class NewRun:
    """All immutable definition data required to record a newly created run."""

    owner_subject_id: UUID
    source_product_id: UUID
    reference_product_id: UUID
    parameters_document: dict[str, object]
    parameters_sha256: str
    code_revision: str
    environment_fingerprint: str
    algorithm_versions: dict[str, object] = field(default_factory=dict)
    model_versions: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject a malformed frozen-parameter identity before a write begins."""

        if not self.parameters_document:
            raise ValueError("parameters_document must not be empty")
        validate_sha256(self.parameters_sha256, field_name="parameters_sha256")


class RunRepository:
    """Write only state/event pairings; it is intentionally not a CRUD facade."""

    def record_new_run(self, session: SessionWriter, command: NewRun) -> Run:
        """Stage a run and its ``run.created`` event in the same transaction.

        This method does not flush or commit.  The caller must use a shared
        transaction (or ``atomic_unit_of_work``) so neither record can survive
        without the other.
        """

        run = Run(
            id=uuid4(),
            owner_subject_id=command.owner_subject_id,
            source_product_id=command.source_product_id,
            reference_product_id=command.reference_product_id,
            parameters_document=command.parameters_document,
            parameters_sha256=command.parameters_sha256,
            algorithm_versions=command.algorithm_versions,
            model_versions=command.model_versions,
            execution_state=ExecutionState.CREATED.value,
            state_version=0,
            event_sequence=1,
            code_revision=command.code_revision,
            environment_fingerprint=command.environment_fingerprint,
        )
        event = RunEvent(
            run_id=run.id,
            event_type="run.created",
            execution_state=ExecutionState.CREATED.value,
            sequence=1,
            event_document={"execution_state": ExecutionState.CREATED.value},
        )
        session.add(run)
        session.add(event)
        return run

    def transition_execution_state(
        self,
        session: Session,
        run: Run,
        target: ExecutionState,
        *,
        actor_subject_id: UUID | None = None,
        event_document: dict[str, object] | None = None,
    ) -> RunEvent:
        """Atomically stage a valid state change and its ordered event.

        The conditional update is the optimistic lock: only a caller that still
        owns the current state version increments both counters.  PostgreSQL
        serialises that row update, and the matching event is added only after a
        successful result.  A caller must retain ownership of the surrounding
        transaction so event insertion and the conditional update commit or
        roll back together.
        """

        current = ExecutionState(run.execution_state)
        validate_execution_transition(current, target)
        extra_document = event_document or {}
        reserved_fields = _RESERVED_EVENT_DOCUMENT_FIELDS.intersection(extra_document)
        if reserved_fields:
            field_list = ", ".join(sorted(reserved_fields))
            raise ReservedEventDocumentFieldError(
                f"event_document cannot override authoritative fields: {field_list}"
            )

        expected_version = run.state_version
        update_result = session.execute(
            update(Run)
            .where(
                Run.id == run.id,
                Run.execution_state == current.value,
                Run.state_version == expected_version,
            )
            .values(
                execution_state=target.value,
                state_version=Run.state_version + 1,
                event_sequence=Run.event_sequence + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(Run.state_version, Run.event_sequence)
        ).one_or_none()
        if update_result is None:
            raise ConcurrentRunTransitionError(
                f"run {run.id} changed before {current.value} -> {target.value} could be recorded"
            )

        next_state_version = update_result[0]
        next_event_sequence = update_result[1]
        # The conditional SQL write already changed the row.  Synchronise this
        # caller's instance as committed state so its flush cannot emit a
        # second, unguarded update after the optimistic predicate succeeded.
        set_committed_value(run, "execution_state", target.value)
        set_committed_value(run, "state_version", next_state_version)
        set_committed_value(run, "event_sequence", next_event_sequence)
        event = RunEvent(
            run_id=run.id,
            actor_subject_id=actor_subject_id,
            event_type="run.execution_state_changed",
            execution_state=target.value,
            sequence=next_event_sequence,
            event_document={
                "from_execution_state": current.value,
                "to_execution_state": target.value,
                **extra_document,
            },
        )
        session.add(event)
        return event

    def record_review(
        self,
        session: Session,
        run: Run,
        *,
        actor_subject_id: UUID,
        decision: str,
        reason_code: str,
        note: str | None,
    ) -> Review:
        """Append an immutable review and matching provenance event atomically.

        A review never changes ``computed_verdict``.  Only a run whose
        independently-computed verdict is ``review`` can use a human decision
        as its effective disposition.  The conditional event-counter update
        prevents concurrent review/lifecycle writers from allocating the same
        history sequence; the losing request must retry from fresh state.
        """

        expected_sequence = run.event_sequence
        effective_disposition = _effective_disposition_after_review(
            run.computed_verdict,
            decision,
        )
        update_result = session.execute(
            update(Run)
            .where(Run.id == run.id, Run.event_sequence == expected_sequence)
            .values(
                effective_disposition=effective_disposition,
                event_sequence=Run.event_sequence + 1,
                updated_at=func.current_timestamp(),
            )
            .returning(Run.event_sequence)
        ).scalar_one_or_none()
        if update_result is None:
            raise ConcurrentReviewSubmissionError(
                f"run {run.id} changed before its review could be recorded"
            )

        set_committed_value(run, "effective_disposition", effective_disposition)
        set_committed_value(run, "event_sequence", update_result)
        review = Review(
            id=uuid4(),
            run_id=run.id,
            actor_subject_id=actor_subject_id,
            decision=decision,
            reason_code=reason_code,
            note=note,
            source_computed_verdict=run.computed_verdict,
        )
        event = RunEvent(
            run_id=run.id,
            actor_subject_id=actor_subject_id,
            event_type="run.review_submitted",
            execution_state=run.execution_state,
            sequence=update_result,
            event_document={
                "decision": decision,
                "effective_disposition": effective_disposition,
                "reason_code": reason_code,
                "review_id": str(review.id),
                "source_computed_verdict": run.computed_verdict,
            },
        )
        session.add(review)
        session.add(event)
        return review


def _effective_disposition_after_review(
    computed_verdict: str | None,
    decision: str,
) -> str:
    """Apply the immutable verdict/review separation from the core contract."""

    if computed_verdict == "accept":
        return "accepted"
    if computed_verdict == "reject":
        return "rejected"
    if computed_verdict == "review":
        return decision
    return "pending"
