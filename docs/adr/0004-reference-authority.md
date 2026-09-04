# ADR-0004: Reference authority and uncertainty propagation

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-03 reference bundle; WP-08 adjustment weighting; WP-09 absolute-accuracy claims
- **Related decisions:** D-002, R-006

## Context

LRO NAC and SELENE TC are image references with their own error, not a datum. The system must distinguish image reference from geodetic control, propagate reference and control uncertainty into weights and reported metrics, and refuse an absolute metre claim without a named control realisation and uncertainty budget.

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
