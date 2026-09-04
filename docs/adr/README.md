# Architecture decision records

Section 5.3 of the implementation plan requires each of these ADRs to be
accepted **before** the code it governs is merged. Four (ADR-0001, ADR-0005,
ADR-0006, ADR-0013) govern code that is already merged and tested and are now
`accepted`, with a decision recorded. The remaining eleven govern code that
does not exist in this repository yet and stay `proposed` with no decision
recorded.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-0001](0001-pixel-centre-convention.md) | Internal pixel-centre convention and named ISIS/GDAL conversions | accepted |
| [ADR-0002](0002-lunar-frame-and-crs.md) | Lunar body-fixed frame, map projection selection, and CRS serialization | proposed |
| [ADR-0003](0003-metric-frames.md) | Source-frame versus reference-frame metric definitions | proposed |
| [ADR-0004](0004-reference-authority.md) | Reference authority and uncertainty propagation | proposed |
| [ADR-0005](0005-import-boundaries.md) | Package import boundaries | accepted |
| [ADR-0006](0006-immutability-and-provenance.md) | Immutable inputs, stage results, and provenance hashing | accepted |
| [ADR-0007](0007-matcher-contract.md) | Matcher plugin and common correspondence contract | proposed |
| [ADR-0008](0008-eligibility-and-coverage.md) | Eligibility mask and spatial-coverage definition | proposed |
| [ADR-0009](0009-adjustment-parameterization.md) | Adjustment parameterization and observability limits | proposed |
| [ADR-0010](0010-verdict-semantics.md) | Verdict semantics and fail-closed rules | proposed |
| [ADR-0011](0011-benchmark-splits.md) | Benchmark split and leakage prevention | proposed |
| [ADR-0012](0012-iirs-processing.md) | IIRS thermal/structural processing and unsupported-band policy | proposed |
| [ADR-0013](0013-stage-lifecycle.md) | Stage resume, retry, cancellation, atomic publication, and downstream invalidation | accepted |
| [ADR-0014](0014-service-state-authority.md) | Service state authority, minimum persistence model, and transaction boundaries | accepted |
| [ADR-0015](0015-network-boundary.md) | Loopback-only versus authenticated network service boundary | proposed |
| [ADR-0016](0016-session-authentication-and-roles.md) | Session-based operator authentication and role model | proposed |

Use [`0000-template.md`](0000-template.md) for new records. An ADR without an
enforcement mechanism in its Verification section is a preference, not a
decision.

## Decision register

Section 4 of the implementation plan tracks D-001 through D-010, the open data,
control, and interface unknowns. Resolving one of those produces an ADR or a
benchmark-manifest revision. Several ADRs above are blocked on a specific
D-item; each names its dependency.
