# ADR-0010: Verdict semantics and fail-closed rules

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-09 verdict engine; WP-10 review workflow
- **Related decisions:** D-008

## Context

Execution state, computed scientific verdict, and human disposition are separate. A missing applicable hard-gate metric is a rejection rather than a pass, an execution failure receives no fabricated verdict, and a review appends a decision without rewriting computed values.

## Decision

Not yet made. This ADR must be accepted before the code it governs is merged
(implementation plan section 5.3).

## Consequences

To be recorded with the decision.

## Verification

To be recorded with the decision. Every ADR needs an enforcement mechanism: a
test, a CI contract, a schema constraint, or a stated review rule.

## Alternatives considered

To be recorded with the decision.
