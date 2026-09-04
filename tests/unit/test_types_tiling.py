"""Tests for tiling and tile specification types.

Covers PixelWindow, MergeRule, and TileSpec validation and semantics.
"""

import pytest

from selene_core.types import MergeRule, PixelWindow, TileSpec

pytestmark = pytest.mark.unit


class TestPixelWindow:
    """Tests for PixelWindow half-open coordinate windows."""

    def test_pixel_window_creation(self) -> None:
        """PixelWindow can be created with position and size."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert window.line_start == 10
        assert window.sample_start == 20
        assert window.line_count == 50
        assert window.sample_count == 60

    def test_pixel_window_is_frozen(self) -> None:
        """PixelWindow is immutable."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        with pytest.raises(AttributeError):
            window.line_start = 15  # type: ignore

    def test_pixel_window_has_slots(self) -> None:
        """PixelWindow uses slots, not __dict__."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert not hasattr(window, "__dict__")

    def test_pixel_window_requires_positive_line_count(self) -> None:
        """PixelWindow requires line_count > 0."""
        with pytest.raises(ValueError, match=r"must be non-empty"):
            PixelWindow(line_start=10, sample_start=20, line_count=0, sample_count=60)

    def test_pixel_window_requires_positive_sample_count(self) -> None:
        """PixelWindow requires sample_count > 0."""
        with pytest.raises(ValueError, match=r"must be non-empty"):
            PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=0)

    def test_pixel_window_rejects_negative_line_count(self) -> None:
        """PixelWindow rejects negative line_count."""
        with pytest.raises(ValueError, match=r"must be non-empty"):
            PixelWindow(line_start=10, sample_start=20, line_count=-1, sample_count=60)

    def test_pixel_window_rejects_negative_sample_count(self) -> None:
        """PixelWindow rejects negative sample_count."""
        with pytest.raises(ValueError, match=r"must be non-empty"):
            PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=-1)

    def test_pixel_window_line_stop(self) -> None:
        """line_stop is line_start + line_count."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert window.line_stop == 60

    def test_pixel_window_sample_stop(self) -> None:
        """sample_stop is sample_start + sample_count."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert window.sample_stop == 80

    def test_pixel_window_area(self) -> None:
        """Area is line_count * sample_count."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert window.area_px2 == 3000

    def test_pixel_window_contains_identical(self) -> None:
        """A window contains an identical window."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        assert window.contains(window)

    def test_pixel_window_contains_smaller_inside(self) -> None:
        """A window contains a smaller window inside it."""
        outer = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        inner = PixelWindow(line_start=20, sample_start=30, line_count=20, sample_count=30)
        assert outer.contains(inner)

    def test_pixel_window_does_not_contain_overlapping(self) -> None:
        """A window does not contain an overlapping window that extends beyond it."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        overlapping = PixelWindow(line_start=20, sample_start=30, line_count=50, sample_count=60)
        assert not window.contains(overlapping)

    def test_pixel_window_does_not_contain_disjoint(self) -> None:
        """A window does not contain a disjoint window."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        disjoint = PixelWindow(line_start=100, sample_start=200, line_count=10, sample_count=10)
        assert not window.contains(disjoint)

    def test_pixel_window_intersection_identical(self) -> None:
        """Intersection of identical windows is themselves."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        result = window.intersection(window)
        assert result == window

    def test_pixel_window_intersection_overlapping(self) -> None:
        """Intersection of overlapping windows is their overlap."""
        window1 = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        window2 = PixelWindow(line_start=30, sample_start=40, line_count=50, sample_count=60)
        result = window1.intersection(window2)
        assert result is not None
        assert result.line_start == 30
        assert result.sample_start == 40
        assert result.line_stop == 60
        assert result.sample_stop == 80

    def test_pixel_window_intersection_disjoint(self) -> None:
        """Intersection of disjoint windows is None."""
        window1 = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        window2 = PixelWindow(line_start=100, sample_start=200, line_count=10, sample_count=10)
        result = window1.intersection(window2)
        assert result is None

    def test_pixel_window_intersection_touching_edge(self) -> None:
        """Intersection of windows touching at an edge is None (half-open)."""
        window1 = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        # window2 starts where window1 ends
        window2 = PixelWindow(line_start=60, sample_start=20, line_count=50, sample_count=60)
        result = window1.intersection(window2)
        assert result is None

    def test_pixel_window_intersection_commutative(self) -> None:
        """Window intersection is commutative."""
        window1 = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        window2 = PixelWindow(line_start=30, sample_start=40, line_count=50, sample_count=60)
        result1 = window1.intersection(window2)
        result2 = window2.intersection(window1)
        assert result1 == result2

    def test_pixel_window_padded(self) -> None:
        """Padded window grows by halo on all sides."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        padded = window.padded(5)
        assert padded.line_start == 5
        assert padded.sample_start == 15
        assert padded.line_count == 60
        assert padded.sample_count == 70

    def test_pixel_window_padded_zero_halo(self) -> None:
        """Padded with zero halo is identical."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        padded = window.padded(0)
        assert padded == window

    def test_pixel_window_padded_negative_halo_rejected(self) -> None:
        """Padded with negative halo is rejected."""
        window = PixelWindow(line_start=10, sample_start=20, line_count=50, sample_count=60)
        with pytest.raises(ValueError, match=r"halo_px must not be negative"):
            window.padded(-1)


class TestMergeRule:
    """Tests for MergeRule enumeration."""

    def test_all_merge_rules_are_constructible(self) -> None:
        """Every MergeRule member can be accessed."""
        assert MergeRule.CORE_ONLY
        assert MergeRule.FEATHER_HALO
        assert MergeRule.CONCATENATE
        assert MergeRule.DEDUPLICATE_BY_POSITION


class TestTileSpec:
    """Tests for TileSpec tiling and budget specification."""

    def test_tile_spec_creation(self) -> None:
        """TileSpec can be created with all required parameters."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        assert spec.core_window == core
        assert spec.halo_px == 10
        assert spec.valid_window == valid
        assert spec.merge_rule == MergeRule.CORE_ONLY
        assert spec.memory_budget_bytes == 1024 * 1024
        assert spec.scratch_budget_bytes == 512 * 1024

    def test_tile_spec_is_frozen(self) -> None:
        """TileSpec is immutable."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        with pytest.raises(AttributeError):
            spec.core_window = core  # type: ignore

    def test_tile_spec_has_slots(self) -> None:
        """TileSpec uses slots, not __dict__."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        assert not hasattr(spec, "__dict__")

    def test_tile_spec_requires_non_negative_halo(self) -> None:
        """TileSpec requires halo_px >= 0."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        with pytest.raises(ValueError, match=r"halo_px must not be negative"):
            TileSpec(
                core_window=core,
                halo_px=-1,
                valid_window=valid,
                merge_rule=MergeRule.CORE_ONLY,
                memory_budget_bytes=1024 * 1024,
                scratch_budget_bytes=512 * 1024,
            )

    def test_tile_spec_requires_positive_memory_budget(self) -> None:
        """TileSpec requires memory_budget_bytes > 0."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        with pytest.raises(ValueError, match=r"memory_budget_bytes must be positive"):
            TileSpec(
                core_window=core,
                halo_px=10,
                valid_window=valid,
                merge_rule=MergeRule.CORE_ONLY,
                memory_budget_bytes=0,
                scratch_budget_bytes=512 * 1024,
            )

    def test_tile_spec_requires_non_negative_scratch_budget(self) -> None:
        """TileSpec requires scratch_budget_bytes >= 0."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        with pytest.raises(ValueError, match=r"scratch_budget_bytes must not be negative"):
            TileSpec(
                core_window=core,
                halo_px=10,
                valid_window=valid,
                merge_rule=MergeRule.CORE_ONLY,
                memory_budget_bytes=1024 * 1024,
                scratch_budget_bytes=-1,
            )

    def test_tile_spec_allows_zero_scratch_budget(self) -> None:
        """TileSpec allows scratch_budget_bytes = 0."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=0,
        )
        assert spec.scratch_budget_bytes == 0

    def test_tile_spec_requires_valid_window_in_padded_core(self) -> None:
        """TileSpec requires valid_window to be contained in padded core window."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        # Valid window escapes the padded core
        valid = PixelWindow(line_start=-20, sample_start=10, line_count=236, sample_count=236)
        with pytest.raises(ValueError, match=r"valid_window must lie within the padded window"):
            TileSpec(
                core_window=core,
                halo_px=10,
                valid_window=valid,
                merge_rule=MergeRule.CORE_ONLY,
                memory_budget_bytes=1024 * 1024,
                scratch_budget_bytes=512 * 1024,
            )

    def test_tile_spec_padded_window_property(self) -> None:
        """padded_window is core window plus halo."""
        core = PixelWindow(line_start=10, sample_start=20, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=20, line_count=256, sample_count=256)
        spec = TileSpec(
            core_window=core,
            halo_px=5,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        padded = spec.padded_window
        assert padded.line_start == 5
        assert padded.sample_start == 15
        assert padded.line_count == 266
        assert padded.sample_count == 266

    def test_tile_spec_read_area(self) -> None:
        """read_area_px2 is padded window area."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        # padded window is 276 x 276
        assert spec.read_area_px2 == 276 * 276

    def test_tile_spec_halo_overhead_ratio(self) -> None:
        """halo_overhead_ratio is read area / core area."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        # padded = 276x276, core = 256x256
        # ratio = (276*276) / (256*256)
        expected_ratio = (276 * 276) / (256 * 256)
        assert spec.halo_overhead_ratio == pytest.approx(expected_ratio)

    def test_tile_spec_zero_halo_overhead_ratio(self) -> None:
        """With zero halo, overhead ratio is 1."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        spec = TileSpec(
            core_window=core,
            halo_px=0,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        assert spec.halo_overhead_ratio == pytest.approx(1.0)

    def test_tile_spec_valid_window_at_padded_edge(self) -> None:
        """TileSpec allows valid_window at the edge of padded core."""
        core = PixelWindow(line_start=10, sample_start=10, line_count=100, sample_count=100)
        # Padded core: [0, 20] x [0, 20]
        # Valid window at exact boundary
        valid = PixelWindow(line_start=0, sample_start=0, line_count=120, sample_count=120)
        spec = TileSpec(
            core_window=core,
            halo_px=10,
            valid_window=valid,
            merge_rule=MergeRule.CORE_ONLY,
            memory_budget_bytes=1024 * 1024,
            scratch_budget_bytes=512 * 1024,
        )
        assert spec.padded_window.contains(spec.valid_window)

    def test_tile_spec_all_merge_rules_constructible(self) -> None:
        """TileSpec can be created with each MergeRule."""
        core = PixelWindow(line_start=0, sample_start=0, line_count=256, sample_count=256)
        valid = PixelWindow(line_start=10, sample_start=10, line_count=236, sample_count=236)
        for merge_rule in MergeRule:
            spec = TileSpec(
                core_window=core,
                halo_px=10,
                valid_window=valid,
                merge_rule=merge_rule,
                memory_budget_bytes=1024 * 1024,
                scratch_budget_bytes=512 * 1024,
            )
            assert spec.merge_rule == merge_rule
