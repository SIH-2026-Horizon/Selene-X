# ADR-0002: Lunar body-fixed frame, map projection selection, and CRS serialization

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-03 reference preparation; WP-09 raster and geometry writers
- **Related decisions:** D-002, R-010

## Context

Every raster and geometry artefact must serialise a full lunar CRS. Per-scene projection selection has to remain valid at the poles and across the longitude wrap, and an Earth datum must never reach an output file.

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
