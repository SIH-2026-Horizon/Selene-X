"""Typed tiled matching with deterministic, auditable overlap resolution.

Algorithms continue to implement the small :class:`~selene_core.match.protocol.Matcher`
array ABI.  This module supplies the scientific orchestration layer around
them: pyramid-level inputs, eligibility masks, tile provenance, memory-budget
checks, coordinate translation, and *record-preserving* deduplication.  It is
important that duplicates are marked rejected rather than silently discarded:
the latter makes a tiled run irreproducible from its output catalogue.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.geometry.pyramid import PairedPyramidLevel
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior
from selene_core.types import PixelWindow, ReferencePixel, SourcePixel, TileSpec

__all__ = [
    "MatchTile",
    "TiledMatchResult",
    "deduplicate_tile_records",
    "match_pyramid_tiles",
]


@dataclass(frozen=True, slots=True)
class MatchTile:
    """One paired pyramid tile in a common pixel frame.

    ``source_window`` and ``reference_window`` locate the supplied arrays in
    their respective level grids.  Their counts must equal the pair's image
    shape; starts may differ where a geometry prior predicts a crop offset.
    """

    tile_id: str
    pyramid_level: int
    level: PairedPyramidLevel
    source_window: PixelWindow
    reference_window: PixelWindow
    tile_spec: TileSpec | None = None

    def __post_init__(self) -> None:
        if not self.tile_id.strip():
            raise ValueError("MatchTile.tile_id must be non-empty")
        if self.pyramid_level < 0:
            raise ValueError("MatchTile.pyramid_level must be non-negative")
        shape = self.level.source.image.shape
        if self.level.reference.image.shape != shape:
            raise ValueError("MatchTile requires same-shaped paired pyramid images")
        expected = (self.source_window.line_count, self.source_window.sample_count)
        if shape != expected:
            raise ValueError("MatchTile.source_window counts must match paired image shape")
        expected_reference = (
            self.reference_window.line_count,
            self.reference_window.sample_count,
        )
        if shape != expected_reference:
            raise ValueError("MatchTile.reference_window counts must match paired image shape")
        if self.tile_spec is not None and not self.tile_spec.valid_window.contains(
            self.source_window
        ):
            raise ValueError("MatchTile.source_window must lie in TileSpec.valid_window")

    @property
    def source_mask(self) -> npt.NDArray[np.bool_] | None:
        return self.level.source.eligibility_mask

    @property
    def reference_mask(self) -> npt.NDArray[np.bool_] | None:
        return self.level.reference.eligibility_mask


@dataclass(frozen=True, slots=True)
class TiledMatchResult:
    """All candidates from a tiled match, including overlap rejections."""

    records: tuple[CorrespondenceRecord, ...]
    tiles_attempted: int
    tiles_with_candidates: int

    @property
    def accepted_count(self) -> int:
        return sum(record.rejection_reason is None for record in self.records)

    @property
    def rejected_count(self) -> int:
        return len(self.records) - self.accepted_count


def _translate_record(record: CorrespondenceRecord, tile: MatchTile) -> CorrespondenceRecord:
    """Move an algorithm-local record into the source/reference level frames."""
    return record.model_copy(
        update={
            "tile_id": tile.tile_id,
            "pyramid_level": tile.pyramid_level,
            "source_pixel": SourcePixel(
                line=record.source_pixel.line + tile.source_window.line_start,
                sample=record.source_pixel.sample + tile.source_window.sample_start,
            ),
            "reference_pixel": ReferencePixel(
                line=record.reference_pixel.line + tile.reference_window.line_start,
                sample=record.reference_pixel.sample + tile.reference_window.sample_start,
            ),
        }
    )


def _pair_distance(first: CorrespondenceRecord, second: CorrespondenceRecord) -> float:
    return max(
        math.hypot(
            first.source_pixel.line - second.source_pixel.line,
            first.source_pixel.sample - second.source_pixel.sample,
        ),
        math.hypot(
            first.reference_pixel.line - second.reference_pixel.line,
            first.reference_pixel.sample - second.reference_pixel.sample,
        ),
    )


def deduplicate_tile_records(
    records: Iterable[CorrespondenceRecord], *, radius_px: float
) -> tuple[CorrespondenceRecord, ...]:
    """Mark halo duplicates with a deterministic winner and explicit reason.

    The winner is highest raw score, then lowest pyramid level, then lexical
    tile and match identity.  This ordering makes results independent of tile
    scheduling.  A record that is already rejected stays rejected; it is not
    allowed to become a winner merely because it scored highly.
    """
    if not math.isfinite(radius_px) or radius_px < 0:
        raise ValueError("radius_px must be finite and non-negative")
    ordered = tuple(records)
    active = [index for index, item in enumerate(ordered) if item.rejection_reason is None]
    active.sort(
        key=lambda index: (
            -ordered[index].raw_score,
            ordered[index].pyramid_level if ordered[index].pyramid_level is not None else -1,
            ordered[index].tile_id or "",
            ordered[index].match_id,
        )
    )
    suppressed: dict[int, str] = {}
    winners: list[int] = []
    for index in active:
        colliding = next(
            (
                winner
                for winner in winners
                if _pair_distance(ordered[index], ordered[winner]) <= radius_px
            ),
            None,
        )
        if colliding is None:
            winners.append(index)
        else:
            winner = ordered[colliding]
            suppressed[index] = (
                "tiled overlap duplicate; retained "
                f"{winner.tile_id or 'untiled'}:{winner.match_id} by deterministic score order"
            )
    return tuple(
        record.model_copy(
            update={
                "is_candidate": False,
                "is_inlier": False,
                "point_role": PointRole.REJECTED,
                "rejection_reason": suppressed[index],
            }
        )
        if index in suppressed
        else record
        for index, record in enumerate(ordered)
    )


def match_pyramid_tiles(
    matcher: Matcher,
    tiles: Iterable[MatchTile],
    *,
    prior: MatchPrior,
    parameters: MatchParameters,
    job_id: str,
    input_digest: str,
    reference_digest: str,
    deduplication_radius_px: float = 0.5,
) -> TiledMatchResult:
    """Run a matcher over typed paired tiles and preserve every produced record.

    A tile's eligibility masks are supplied directly to the matcher, so masked
    pixels can never be converted into match features by orchestration.  The
    function does not manufacture a "real report" from these diagnostics;
    callers may only use its explicit candidate records as input to a measured
    benchmark runner.
    """
    tile_tuple = tuple(tiles)
    seen_ids: set[tuple[int, str]] = set()
    translated: list[CorrespondenceRecord] = []
    tiles_with_candidates = 0
    for tile in tile_tuple:
        identity = (tile.pyramid_level, tile.tile_id)
        if identity in seen_ids:
            raise ValueError(f"duplicate MatchTile identity {identity!r}")
        seen_ids.add(identity)
        if tile.tile_spec is not None:
            bytes_required = tile.level.source.image.nbytes + tile.level.reference.image.nbytes
            if bytes_required > tile.tile_spec.memory_budget_bytes:
                raise ValueError("MatchTile image bytes exceed TileSpec.memory_budget_bytes")
        local_records = matcher.match(
            tile.level.source.image,
            tile.level.reference.image,
            source_mask=tile.source_mask,
            reference_mask=tile.reference_mask,
            prior=prior,
            parameters=parameters,
            job_id=job_id,
            input_digest=input_digest,
            reference_digest=reference_digest,
        )
        if local_records:
            tiles_with_candidates += 1
        translated.extend(_translate_record(record, tile) for record in local_records)
    return TiledMatchResult(
        records=deduplicate_tile_records(translated, radius_px=deduplication_radius_px),
        tiles_attempted=len(tile_tuple),
        tiles_with_candidates=tiles_with_candidates,
    )
