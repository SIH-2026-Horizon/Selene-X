"""Tests for time types.

Covers EphemerisTime and AcquisitionInterval with proper UTC/ET distinction,
timezone awareness, and duration validation.
"""

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest

from selene_core.types import AcquisitionInterval, EphemerisTime

pytestmark = pytest.mark.unit


class TestEphemerisTime:
    """Tests for SPICE ephemeris time representation."""

    def test_ephemeris_time_creation(self) -> None:
        """EphemerisTime can be created with seconds since J2000."""
        et = EphemerisTime(et_s=0.0)
        assert et.et_s == 0.0

    def test_ephemeris_time_is_frozen(self) -> None:
        """EphemerisTime is immutable."""
        et = EphemerisTime(et_s=100.0)
        with pytest.raises(AttributeError):
            et.et_s = 200.0  # type: ignore

    def test_ephemeris_time_has_slots(self) -> None:
        """EphemerisTime uses slots, not __dict__."""
        et = EphemerisTime(et_s=100.0)
        assert not hasattr(et, "__dict__")

    def test_ephemeris_time_rejects_nan(self) -> None:
        """EphemerisTime rejects NaN."""
        with pytest.raises(ValueError, match=r"EphemerisTime.et_s must be finite"):
            EphemerisTime(et_s=math.nan)

    def test_ephemeris_time_rejects_inf(self) -> None:
        """EphemerisTime rejects positive infinity."""
        with pytest.raises(ValueError, match=r"EphemerisTime.et_s must be finite"):
            EphemerisTime(et_s=math.inf)

    def test_ephemeris_time_rejects_negative_inf(self) -> None:
        """EphemerisTime rejects negative infinity."""
        with pytest.raises(ValueError, match=r"EphemerisTime.et_s must be finite"):
            EphemerisTime(et_s=-math.inf)

    def test_ephemeris_time_accepts_negative_values(self) -> None:
        """EphemerisTime accepts negative values (before J2000)."""
        et = EphemerisTime(et_s=-86400.0)
        assert et.et_s == -86400.0

    def test_ephemeris_time_accepts_zero(self) -> None:
        """EphemerisTime accepts zero (exactly J2000)."""
        et = EphemerisTime(et_s=0.0)
        assert et.et_s == 0.0


class TestAcquisitionInterval:
    """Tests for UTC acquisition time intervals."""

    def test_acquisition_interval_creation(self) -> None:
        """AcquisitionInterval can be created with start and stop UTC times."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert interval.start_utc == start
        assert interval.stop_utc == stop

    def test_acquisition_interval_is_frozen(self) -> None:
        """AcquisitionInterval is immutable."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        with pytest.raises(AttributeError):
            interval.start_utc = start  # type: ignore

    def test_acquisition_interval_has_slots(self) -> None:
        """AcquisitionInterval uses slots, not __dict__."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert not hasattr(interval, "__dict__")

    def test_acquisition_interval_requires_timezone_aware_start(self) -> None:
        """AcquisitionInterval requires start_utc to be timezone-aware."""
        start = datetime(2024, 1, 1, 12, 0, 0)  # Naive datetime
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match=r"start_utc must be timezone-aware"):
            AcquisitionInterval(start_utc=start, stop_utc=stop)

    def test_acquisition_interval_requires_timezone_aware_stop(self) -> None:
        """AcquisitionInterval requires stop_utc to be timezone-aware."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0)  # Naive datetime
        with pytest.raises(ValueError, match=r"stop_utc must be timezone-aware"):
            AcquisitionInterval(start_utc=start, stop_utc=stop)

    def test_acquisition_interval_requires_utc_start(self) -> None:
        """AcquisitionInterval requires start_utc to be UTC."""
        # Create a timezone offset by 1 hour
        plus_one = timezone(timedelta(hours=1))
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=plus_one)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match=r"start_utc must be expressed in UTC"):
            AcquisitionInterval(start_utc=start, stop_utc=stop)

    def test_acquisition_interval_requires_utc_stop(self) -> None:
        """AcquisitionInterval requires stop_utc to be UTC."""
        plus_one = timezone(timedelta(hours=1))
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=plus_one)
        with pytest.raises(ValueError, match=r"stop_utc must be expressed in UTC"):
            AcquisitionInterval(start_utc=start, stop_utc=stop)

    def test_acquisition_interval_requires_start_before_stop(self) -> None:
        """AcquisitionInterval requires start_utc <= stop_utc."""
        start = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match=r"must not end before it starts"):
            AcquisitionInterval(start_utc=start, stop_utc=stop)

    def test_acquisition_interval_allows_equal_times(self) -> None:
        """AcquisitionInterval allows start_utc == stop_utc (instant)."""
        time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=time, stop_utc=time)
        assert interval.duration_s == 0.0

    def test_acquisition_interval_duration(self) -> None:
        """Duration is correct time difference in seconds."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert interval.duration_s == pytest.approx(60.0)

    def test_acquisition_interval_duration_fractional_seconds(self) -> None:
        """Duration handles fractional seconds."""
        start = datetime(2024, 1, 1, 12, 0, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 0, 0, 500000, tzinfo=UTC)  # 0.5 seconds
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert interval.duration_s == pytest.approx(0.5)

    def test_acquisition_interval_duration_multiple_days(self) -> None:
        """Duration works correctly across days."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 3, 12, 0, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        # 2 days = 2 * 24 * 3600 = 172800 seconds
        assert interval.duration_s == pytest.approx(172800.0)

    def test_acquisition_interval_contains_instant_at_start(self) -> None:
        """contains() returns True for the start moment."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert interval.contains(start)

    def test_acquisition_interval_contains_instant_at_stop(self) -> None:
        """contains() returns True for the stop moment."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        assert interval.contains(stop)

    def test_acquisition_interval_contains_instant_inside(self) -> None:
        """contains() returns True for a moment inside the interval."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        middle = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        assert interval.contains(middle)

    def test_acquisition_interval_contains_instant_before(self) -> None:
        """contains() returns False for a moment before the interval."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        before = datetime(2024, 1, 1, 11, 59, 0, tzinfo=UTC)
        assert not interval.contains(before)

    def test_acquisition_interval_contains_instant_after(self) -> None:
        """contains() returns False for a moment after the interval."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        after = datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC)
        assert not interval.contains(after)

    def test_acquisition_interval_contains_requires_timezone_aware(self) -> None:
        """contains() requires a timezone-aware moment."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        stop = datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=start, stop_utc=stop)
        naive_moment = datetime(2024, 1, 1, 12, 0, 30)
        with pytest.raises(ValueError, match=r"moment_utc must be timezone-aware"):
            interval.contains(naive_moment)

    def test_acquisition_interval_zero_duration(self) -> None:
        """AcquisitionInterval with start == stop has duration 0."""
        time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        interval = AcquisitionInterval(start_utc=time, stop_utc=time)
        assert interval.duration_s == 0.0
        assert interval.contains(time)
