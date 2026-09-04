"""Optional long-stage worker adapters.

Distributed workers are a post-MVP item. Their entry criteria (plan section 13)
are that local jobs are correct, stage boundaries are stable, a measured
concurrency need justifies the queue complexity, and idempotent stage effects
are tested.

Worker adapters carry identifiers and immutable parameter snapshots. They never
accept caller-controlled paths or credentials.
"""

__all__: list[str] = []

__version__ = "0.0.0"
