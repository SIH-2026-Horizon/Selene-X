"""The ``Matcher`` protocol, and its prior/parameter inputs (WP-04 task 1).

**Scope ruling.** ``match/__init__.py``'s docstring describes a ``Matcher``
consuming "typed pyramid tiles, masks, priors, and a parameter snapshot" from
WP-03 (geometry, pyramids, masks) — but WP-03 does not exist in this
repository yet, and neither does ``rasterio``/GDAL. There is no pyramid, no
tile, no real mask infrastructure to consume. This module therefore defines
the protocol at the granularity that is actually buildable now: plain 2D
NumPy arrays (a single image/tile-shaped array, not a tiled pyramid), plus an
explicit optional boolean mask array of the same shape, plus a minimal typed
prior and parameter snapshot. Tiling, halos, deterministic overlap
deduplication, and real pyramid-level consumption are deferred until WP-03
exists to supply them (plan WP-04 task 6).

This module also does not implement any matching algorithm. Task 14 (phase
correlation and NCC) is the first concrete ``Matcher`` implementation against
this contract.

Kept separate from :mod:`selene_core.match.correspondence` because this is a
behavioural contract (an interface an implementation satisfies) rather than a
serialised, schema-bound data contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from selene_core.hashing import digest_json
from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.types import LocalWarpJacobian, SourcePixel

__all__ = [
    "MatchParameters",
    "MatchPrior",
    "Matcher",
    "TiledMatcher",
]


@dataclass(frozen=True, slots=True)
class MatchPrior:
    """A minimal starting hint for a matcher.

    Stands in for the richer WP-03 geometry-derived prior (predicted
    displacement from orbit and pointing solutions, propagated uncertainty)
    that does not exist yet. A matcher that receives no useful prior
    information is passed one with every field ``None``.
    """

    displacement_px: tuple[float, float] | None = None
    """(dy, dx) — line/sample = row/column = y/x order, matching this
    project's established internal pixel convention (selene_core.types)."""

    displacement_uncertainty_px: tuple[float, float] | None = None
    """(dy, dx) one-sigma uncertainty on displacement_px, same axis order."""

    search_radius_px: float | None = None
    """How far from the prior displacement a matcher should search."""

    local_warp_jacobian: LocalWarpJacobian | None = None
    """Optional local source-to-reference scale/affine term.

    The displacement remains defined at ``anchor_source_pixel``.  Keeping the
    affine term separate from the translation makes the line/sample convention
    explicit and lets a coarse matcher use a geometry prior without claiming it
    estimated an affine model itself.
    """

    anchor_source_pixel: SourcePixel = field(
        default_factory=lambda: SourcePixel(line=0.0, sample=0.0)
    )

    def __post_init__(self) -> None:
        for name in ("displacement_px", "displacement_uncertainty_px"):
            pair = getattr(self, name)
            if pair is not None and not all(math.isfinite(component) for component in pair):
                raise ValueError(f"MatchPrior.{name} must be finite, got {pair!r}")
        if self.search_radius_px is not None:
            if not math.isfinite(self.search_radius_px):
                raise ValueError(
                    f"MatchPrior.search_radius_px must be finite, got {self.search_radius_px!r}"
                )
            if self.search_radius_px <= 0.0:
                raise ValueError(
                    f"MatchPrior.search_radius_px must be positive, got {self.search_radius_px!r}"
                )

    def displacement_at(self, source_pixel: SourcePixel) -> tuple[float, float]:
        """Return the geometry-predicted displacement at ``source_pixel``.

        With no affine term this is the constant displacement used by the
        original matcher contract.  With one, ``J - I`` is applied to the
        source offset from the declared anchor, which is the displacement
        induced by a local source-to-reference affine map.
        """
        displacement = self.displacement_px or (0.0, 0.0)
        if self.local_warp_jacobian is None:
            return displacement
        delta_line = source_pixel.line - self.anchor_source_pixel.line
        delta_sample = source_pixel.sample - self.anchor_source_pixel.sample
        mapped_line, mapped_sample = self.local_warp_jacobian.apply(delta_line, delta_sample)
        return (
            displacement[0] + mapped_line - delta_line,
            displacement[1] + mapped_sample - delta_sample,
        )

    def residual_at(
        self, source_pixel: SourcePixel, observed_displacement_px: tuple[float, float]
    ) -> tuple[float, float] | None:
        """Return observed minus predicted displacement, or ``None`` without a prior."""
        if self.displacement_px is None and self.local_warp_jacobian is None:
            return None
        expected = self.displacement_at(source_pixel)
        return (
            observed_displacement_px[0] - expected[0],
            observed_displacement_px[1] - expected[1],
        )


@dataclass(frozen=True, slots=True)
class MatchParameters:
    """The exact parameter set one matcher invocation ran with.

    ``values`` holds whatever a specific matcher implementation needs — for
    example a phase-correlation matcher's window size and sub-pixel
    refinement method, or an NCC matcher's template radius and threshold.
    Kept as a generic name/value mapping rather than named fields because no
    concrete matcher exists yet in this repository (Task 14 is the first);
    a generic contract here avoids re-litigating this class per algorithm.

    ``parameter_set_digest`` is what populates
    :attr:`CorrespondenceRecord.parameter_set_digest`, satisfying WP-04 task
    9's "record every algorithm parameter" requirement: the digest is over
    every value in ``values``, so a run with different parameters is
    provably distinguishable from one that recorded the same digest.
    """

    values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copied into a MappingProxyType so that a caller cannot mutate the
        # dict backing an already-constructed, supposedly-frozen instance,
        # regardless of what kind of Mapping (typically a plain dict) it was
        # constructed with.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def parameter_set_digest(self) -> str:
        """A stable SHA-256 digest over every parameter value.

        Deterministic: the same ``values`` produce the same digest across
        independent constructions, because :func:`digest_json` hashes
        canonical (sorted-key) JSON.
        """
        return digest_json(dict(self.values))


@runtime_checkable
class Matcher(Protocol):
    """The WP-04-task-1 matching contract. Task 14's phase-correlation and
    NCC baselines are the first implementations of this protocol.

    Operates on a single 2D array pair, **not** a tiled pyramid — see this
    module's docstring for why. ``source`` and ``reference`` are plain
    ``float64`` NumPy arrays of one image or tile-shaped region each; they
    need not share a shape.

    Mask polarity is ``True`` means valid/usable, ``False`` means
    invalid/unusable (nodata, shadow, border, terrain gap). This is stated
    explicitly because an inverted mask convention is a classic, easy-to-
    introduce bug: a caller passing a "these pixels are bad" mask where this
    contract expects "these pixels are good" would silently match on garbage.
    """

    def match(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        """Find correspondences between ``source`` and ``reference``.

        Args:
            source: The source image or tile-shaped array, float64.
            reference: The reference image or tile-shaped array, float64.
            source_mask: Boolean array the same shape as ``source``, or
                ``None`` when every source pixel is usable. ``True`` means
                valid/usable.
            reference_mask: Boolean array the same shape as ``reference``,
                or ``None`` when every reference pixel is usable. ``True``
                means valid/usable.
            prior: A starting hint for where to search.
            parameters: The exact parameter set this call runs with; also
                the source of ``CorrespondenceRecord.parameter_set_digest``.
            job_id: Propagated onto every returned record.
            input_digest: SHA-256 of the source array's bytes, propagated
                onto every returned record's ``input_digest``.
            reference_digest: SHA-256 of the reference array's bytes,
                propagated onto every returned record's ``reference_digest``.

        Returns:
            Every candidate this matcher produced, including rejected
            candidates with their rejection reason — a matching stage's
            behaviour is only auditable if the points it threw away are as
            visible as the points it kept.
        """
        ...


@runtime_checkable
class TiledMatcher(Protocol):
    """Optional extension implemented by matchers that accept tiled inputs.

    The compact array ``Matcher`` interface remains the algorithm-level ABI:
    it is deliberately easy to use in tests and optional adapters.  The tiled
    orchestration API lives in :mod:`selene_core.match.tiling` so that all
    algorithms share deterministic overlap handling and provenance.
    """

    def match_tiles(self, *args: object, **kwargs: object) -> tuple[CorrespondenceRecord, ...]:
        """Match typed pyramid tiles and return canonical records."""
        ...
