"""SELENE-XR REST service (WP-10).

The service exposes the same scientific implementation as the CLI. Routers hold
no scientific logic; domain services call ``selene_core``. PostgreSQL/PostGIS is
the sole service-state authority (plan section 5.4, ADR-014).

The unauthenticated development API is constrained to loopback single-user use.
Binding beyond loopback requires an explicitly declared external authentication
boundary; authentication and authorisation implementation remains a later task
(ADR-015).
"""

__all__ = ["__version__"]

__version__ = "0.0.0"
