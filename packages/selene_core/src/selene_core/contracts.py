"""The shared pydantic contract base (plan section 6.5, ADR-0013).

``Contract`` is the frozen, extra-forbid base every serialised data contract
in ``selene_core`` derives from — originally private to
:mod:`selene_core.pipeline.results`, now shared because more than one layer
needs it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["Contract"]


class Contract(BaseModel):
    """Base for every serialised contract in this package.

    ``extra="forbid"`` implements the rule that unknown fields are rejected
    rather than ignored: an ignored field silently changes nothing while
    appearing to change something.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=True)
