"""Enforce the unit-suffix convention declared in ``selene_core.types``'s
module docstring.

Angles carry ``_deg``/``_rad``; distances carry ``_m``/``_m2``/``_px``/``_px2``;
durations carry ``_s``; sizes carry ``_bytes``. Every ``float``/``int`` field
of every public contract dataclass in :mod:`selene_core.types` must carry one
of those suffixes, or be named in ``_EXEMPT_FIELDS`` below with a reason
grounded in the module itself. A new unsuffixed numeric field on one of these
dataclasses that is neither suffixed nor exempted fails this test.
"""

from __future__ import annotations

import dataclasses
from typing import Any, get_type_hints

import pytest

from selene_core import types as selene_types
from selene_core.types import (
    AcquisitionInterval,
    BodyFixedCoordinate,
    Covariance2D,
    EphemerisTime,
    LocalWarpJacobian,
    MapCoordinate,
    PixelWindow,
    ReferencePixel,
    SelenographicCoordinate,
    SourcePixel,
    TileSpec,
)

pytestmark = pytest.mark.unit

# The eight suffixes the module docstring declares.
_SUFFIXES = ("_deg", "_rad", "_m2", "_m", "_px2", "_px", "_s", "_bytes")

# Every public contract dataclass named in __all__. Kept explicit (rather than
# discovered) so that test_contract_dataclass_list_is_exhaustive below can
# fail loudly if a new one is exported and forgotten here.
_CONTRACT_DATACLASSES: tuple[type, ...] = (
    SourcePixel,
    ReferencePixel,
    MapCoordinate,
    BodyFixedCoordinate,
    SelenographicCoordinate,
    LocalWarpJacobian,
    Covariance2D,
    PixelWindow,
    TileSpec,
    EphemerisTime,
    AcquisitionInterval,
)

# Numeric (float/int) fields that legitimately carry no unit suffix, with the
# reason grounded in what the module actually says or does. A field that is
# renamed, removed, or newly suffixed must have its exemption updated too:
# test_exempt_fields_are_actually_unsuffixed_numeric and
# test_every_exemption_names_a_field_that_still_exists both enforce that.
_EXEMPT_FIELDS: dict[tuple[str, str], str] = {
    ("SourcePixel", "line"): (
        "pixel-grid coordinate in the internal centre-referenced convention "
        "(ADR-0001); the SourcePixel type itself fixes the pixel domain, not a "
        "suffix on the field"
    ),
    ("SourcePixel", "sample"): (
        "pixel-grid coordinate in the internal centre-referenced convention "
        "(ADR-0001); the SourcePixel type itself fixes the pixel domain, not a "
        "suffix on the field"
    ),
    ("ReferencePixel", "line"): (
        "pixel-grid coordinate in the internal centre-referenced convention "
        "(ADR-0001); the ReferencePixel type itself fixes the pixel domain, not "
        "a suffix on the field"
    ),
    ("ReferencePixel", "sample"): (
        "pixel-grid coordinate in the internal centre-referenced convention "
        "(ADR-0001); the ReferencePixel type itself fixes the pixel domain, not "
        "a suffix on the field"
    ),
    ("LocalWarpJacobian", "d_ref_line_d_src_line"): (
        "a partial derivative of one pixel coordinate with respect to another "
        "(px/px); dimensionless by construction, per the class's own docstring"
    ),
    ("LocalWarpJacobian", "d_ref_line_d_src_sample"): (
        "a partial derivative of one pixel coordinate with respect to another "
        "(px/px); dimensionless by construction, per the class's own docstring"
    ),
    ("LocalWarpJacobian", "d_ref_sample_d_src_line"): (
        "a partial derivative of one pixel coordinate with respect to another "
        "(px/px); dimensionless by construction, per the class's own docstring"
    ),
    ("LocalWarpJacobian", "d_ref_sample_d_src_sample"): (
        "a partial derivative of one pixel coordinate with respect to another "
        "(px/px); dimensionless by construction, per the class's own docstring"
    ),
    ("Covariance2D", "xx"): (
        "the unit is carried once by the companion `units` field for xx, xy, "
        "and yy together; suffixing each component would duplicate it and let "
        "the two disagree (stated in Covariance2D's own docstring)"
    ),
    ("Covariance2D", "xy"): (
        "the unit is carried once by the companion `units` field for xx, xy, "
        "and yy together; suffixing each component would duplicate it and let "
        "the two disagree (stated in Covariance2D's own docstring)"
    ),
    ("Covariance2D", "yy"): (
        "the unit is carried once by the companion `units` field for xx, xy, "
        "and yy together; suffixing each component would duplicate it and let "
        "the two disagree (stated in Covariance2D's own docstring)"
    ),
    ("PixelWindow", "line_start"): (
        "pixel-grid index in the internal convention; PixelWindow itself fixes "
        "the pixel domain, not a suffix on the field"
    ),
    ("PixelWindow", "sample_start"): (
        "pixel-grid index in the internal convention; PixelWindow itself fixes "
        "the pixel domain, not a suffix on the field"
    ),
    ("PixelWindow", "line_count"): "a count of pixels, not a coordinate or a physical distance",
    ("PixelWindow", "sample_count"): ("a count of pixels, not a coordinate or a physical distance"),
}


def _numeric_fields(cls: type) -> list[dataclasses.Field[Any]]:
    """Return ``cls``'s dataclass fields whose resolved type is float or int."""
    hints = get_type_hints(cls)
    return [field for field in dataclasses.fields(cls) if hints[field.name] in (float, int)]


class TestContractDataclassCoverage:
    """This test's dataclass list must track what the module actually exports."""

    def test_contract_dataclass_list_is_exhaustive(self) -> None:
        """Every dataclass exported from selene_core.types is covered here.

        Guards against a newly added contract dataclass silently skipping
        unit-suffix enforcement.
        """
        exported_dataclasses = {
            name
            for name in selene_types.__all__
            if dataclasses.is_dataclass(getattr(selene_types, name))
        }
        covered = {cls.__name__ for cls in _CONTRACT_DATACLASSES}
        assert exported_dataclasses == covered


class TestUnitSuffixConvention:
    """Every numeric contract field carries a declared suffix or a named exemption."""

    @pytest.mark.parametrize("cls", _CONTRACT_DATACLASSES, ids=lambda c: c.__name__)
    def test_numeric_fields_are_suffixed_or_exempt(self, cls: type) -> None:
        """Angles/distances/durations/sizes must carry a declared suffix, unless exempt."""
        violations = [
            field.name
            for field in _numeric_fields(cls)
            if not field.name.endswith(_SUFFIXES)
            and (cls.__name__, field.name) not in _EXEMPT_FIELDS
        ]
        assert violations == [], (
            f"{cls.__name__} has unsuffixed numeric field(s) {violations} with no "
            f"declared unit suffix {_SUFFIXES} and no entry in _EXEMPT_FIELDS"
        )

    def test_every_exemption_names_a_field_that_still_exists(self) -> None:
        """A stale exemption for a renamed or removed field must be caught."""
        all_field_names = {
            (cls.__name__, field.name)
            for cls in _CONTRACT_DATACLASSES
            for field in dataclasses.fields(cls)
        }
        stale = sorted(set(_EXEMPT_FIELDS) - all_field_names)
        assert stale == [], f"exemptions reference fields that no longer exist: {stale}"

    def test_exempt_fields_are_actually_unsuffixed_numeric(self) -> None:
        """Every exemption names a real float/int field that lacks a suffix.

        Guards against an exemption becoming dead weight, or masking a field
        that was later given a suffix and no longer needs one.
        """
        by_class = {cls.__name__: cls for cls in _CONTRACT_DATACLASSES}
        for class_name, field_name in _EXEMPT_FIELDS:
            cls = by_class[class_name]
            hints = get_type_hints(cls)
            assert hints[field_name] in (float, int), (
                f"{class_name}.{field_name} is exempted as numeric but its type is "
                f"{hints[field_name]!r}"
            )
            assert not field_name.endswith(_SUFFIXES), (
                f"{class_name}.{field_name} is exempted but already carries a suffix; "
                "remove the now-unnecessary exemption"
            )
