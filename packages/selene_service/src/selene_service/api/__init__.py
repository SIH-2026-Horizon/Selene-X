"""HTTP routers and the OpenAPI contract (WP-10 tasks 3 and 4).

Routers translate between HTTP and domain services. They contain no scientific
logic and invent no metric or state absent from the core result.

The contract must cover products, uploads, re-validation, preflight, jobs,
cancellation, retry and resume, stage and result status, reviews, geometry,
metrics, matches, artefacts, health and version, and output validation
(plan section 8).
"""

__all__: list[str] = []
