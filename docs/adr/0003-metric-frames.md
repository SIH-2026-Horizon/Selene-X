# ADR-0003: Source-frame versus reference-frame metric definitions

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-08 adjustment diagnostics; WP-09 metric reports
- **Related decisions:** D-007

## Context

The challenge evaluates sub-pixel correspondence in the source-image frame. Residuals computed in a reference frame need the local warp Jacobian to convert, and mixing the two silently changes what a reported RMSE means.

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
