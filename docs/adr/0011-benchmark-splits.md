# ADR-0011: Benchmark split and leakage prevention

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-00 governance; WP-06 training and adaptation; every accuracy claim
- **Related decisions:** D-001, D-007, R-011

## Context

Geographic leakage between splits invalidates held-out accuracy. Spatially related crops, repeated acquisitions, and same-terrain products must stay in one split, and synthetic data derived from held-out regions must not reach training.

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
