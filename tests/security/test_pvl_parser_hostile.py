"""Hostile-input fixture suite for the ISIS/PVL label parser (WP-02 task 12).

Every fixture below is literal bytes constructed in this file — none are
downloaded or read from an external file, so the suite exercises exactly the
attack shape it claims to and nothing environment-dependent.

Unlike the PDS4 XML parser's hostile suite (`test_pds4_parser_hostile.py`),
there is no entity-expansion or external-reference attack class to test
here: PVL has no such mechanism (see `selene_core.ingest.pvl`'s module
docstring). The risks tested below are purely structural — nesting depth,
sequence/set size, statement count, and plain oversized input — plus the
proof that a `^POINTER` value is extracted as literal data without ever
touching the filesystem.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from selene_core.ingest.pvl import (
    PvlParseError,
    PvlParseLimits,
    PvlQuantity,
    _tokenize,
    _TokenStream,
    parse_pvl_label,
)
from selene_core.pipeline.failures import FailureCode

pytestmark = pytest.mark.security


# --------------------------------------------------------------------------
# Required fixtures (task brief)
# --------------------------------------------------------------------------


def test_deeply_nested_object_group_hits_depth_limit() -> None:
    """A depth/stack bomb: 10,000 layers of `Object = A` ... `End_Object`.

    No entity mechanism is involved (PVL has none); this is pure structural
    nesting. Must be rejected once `max_depth` is exceeded, with the
    default `PvlParseLimits` (`max_depth=16`), which this document blows
    past by three orders of magnitude.
    """
    depth = 10_000
    label = ("Object = A\n" * depth + "End_Object\n" * depth + "End\n").encode()

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "depth" in excinfo.value.message.lower()


def test_depth_limit_is_enforced_during_parsing_not_after_full_materialization() -> None:
    """Directly demonstrates the depth check interrupts the parse partway
    through, the same way `test_pds4_parser_hostile
    .test_depth_limit_is_enforced_during_parsing_not_after_full_materialization`
    proves it for the XML parser.

    Drives the tokenizer/parser internals directly: feeds a document 10,000
    layers deep with `max_depth=64` and asserts the parser's `stack` never
    grew past `max_depth` entries before raising — proving the exception
    was raised on the 65th `Object =` statement, not after all 10,000 open
    statements had already been read and a full nested dict built.
    """
    from selene_core.ingest.pvl import _parse_statements

    limits = PvlParseLimits(max_depth=64)
    depth = 10_000
    label = "Object = A\n" * depth + "End_Object\n" * depth + "End\n"
    stream = _TokenStream(_tokenize(label))

    # `_parse_statements` raises as soon as pushing the 65th frame would
    # exceed `max_depth`, so the recorded depth in the exception is exactly
    # one past the limit — proof it stopped on the 65th `Object =`
    # statement, not after all 10,000 had already been read and a full
    # nested dict built.
    with pytest.raises(PvlParseError) as excinfo:
        _parse_statements(stream, limits)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert excinfo.value.context["depth"] == limits.max_depth + 1


def test_excessive_statement_count_hits_statement_limit() -> None:
    """A wide bomb: many thousands of top-level `Keyword_N = value`
    statements, each individually cheap, but far exceeding
    `max_statements`.
    """
    statements = "\n".join(f"Keyword_{i} = {i}" for i in range(50_000))
    label = (statements + "\nEnd\n").encode()

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "statement" in excinfo.value.message.lower()


def test_excessive_sequence_element_count_hits_sequence_limit() -> None:
    """A single value `Keyword = (1, 2, 3, ..., 100000)` — one statement,
    but a sequence far exceeding `max_sequence_items`.
    """
    items = ", ".join(str(i) for i in range(100_000))
    label = f"Keyword = ({items})\nEnd\n".encode()

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "sequence" in excinfo.value.message.lower()


def test_oversized_input_is_rejected_before_any_tokenizing_work() -> None:
    """The raw-size cap: rejected fast, before decoding or tokenizing runs.

    Uses a document that would be expensive to actually tokenize (millions
    of statements, well over the default `max_bytes`) and asserts the whole
    call still completes quickly — proof the size check runs first and does
    no other work on the oversized input.
    """
    label = b"Keyword = 1\n" * 1_000_000  # >5 MiB, would be slow to tokenize fully
    assert len(label) > PvlParseLimits().max_bytes

    started = time.perf_counter()
    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)
    elapsed = time.perf_counter() - started

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "bytes" in excinfo.value.message.lower()
    assert elapsed < 1.0


def test_unterminated_string_is_rejected_not_a_crash_or_hang() -> None:
    """An opening quote with no closing quote is malformed, not hostile."""
    label = b'Keyword = "unterminated value\nEnd\n'

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE
    assert "unterminated" in excinfo.value.message.lower()


def test_more_end_object_than_object_opened_is_unparseable() -> None:
    """More `End_Object`s than `Object`s were opened."""
    label = b"Object = A\nKeyword = 1\nEnd_Object\nEnd_Object\nEnd\n"

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE
    assert "no matching" in excinfo.value.message.lower()


def test_object_never_closed_before_end_is_unparseable() -> None:
    """An `Object` opened but never closed before a bare `End` terminates
    the label.
    """
    label = b"Object = A\nKeyword = 1\nEnd\n"

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE
    assert "never closed" in excinfo.value.message.lower()


def test_pointer_bearing_label_parses_without_touching_the_filesystem(tmp_path: Path) -> None:
    """A `^POINTER`-bearing label parses successfully, and the parser never
    opens the file it names.

    The pointer target is an absolute path inside `tmp_path` that is
    deliberately never created. If `parse_pvl_label` ever tried to open it,
    it would raise `OSError` (the file provably does not exist) instead of
    returning successfully — that failure mode not occurring is the proof
    no file access was attempted, with no mocking required.
    """
    missing_file = tmp_path / "nonexistent-file-that-would-error-if-opened.img"
    assert not missing_file.exists()

    label = (
        f'^IMAGE = ("{missing_file}", 65)\n'
        "Object = IsisCube\n"
        "  Group = Dimensions\n"
        "    Samples = 100\n"
        "  End_Group\n"
        "End_Object\n"
        "End\n"
    ).encode()

    result = parse_pvl_label(label)

    assert result["^IMAGE"] == [str(missing_file), 65]
    assert result["IsisCube"]["Dimensions"]["Samples"] == 100
    assert not missing_file.exists()  # still never created/touched


def test_synthetic_isis_shaped_label_parses_to_expected_structure() -> None:
    """A small, well-formed, ISIS-shaped label parses successfully and
    returns the expected nested structure.

    This is a synthetic fixture invented for this test suite, not a real
    ISIS cube label — no real mission label content appears anywhere in
    this file.
    """
    label = (
        b"Object = IsisCube\n"
        b"  Group = Dimensions\n"
        b"    Samples = 512\n"
        b"    Lines   = 512\n"
        b"    Bands   = 1\n"
        b"  End_Group\n"
        b"  Group = Instrument\n"
        b'    SpacecraftName = "Chandrayaan-2"\n'
        b"    FocalLength = 685.0 <mm>\n"
        b"  End_Group\n"
        b"End_Object\n"
        b"End\n"
    )

    result = parse_pvl_label(label)

    assert result["IsisCube"]["Dimensions"]["Samples"] == 512
    assert result["IsisCube"]["Dimensions"]["Lines"] == 512
    assert result["IsisCube"]["Dimensions"]["Bands"] == 1
    assert result["IsisCube"]["Instrument"]["SpacecraftName"] == "Chandrayaan-2"
    assert result["IsisCube"]["Instrument"]["FocalLength"] == PvlQuantity(685.0, "mm")


def test_comments_are_stripped_and_do_not_affect_parsing() -> None:
    """A label with `/* ... */` and `#`-to-end-of-line comments interleaved
    parses to the same structure as the same label with comments removed.
    """
    with_comments = (
        b"/* leading block comment */\n"
        b"Object = IsisCube # trailing line comment\n"
        b"  Group = Dimensions /* inline block */\n"
        b"    Samples = 512 # a comment on a value line\n"
        b"  End_Group\n"
        b"End_Object\n"
        b"End\n"
    )
    without_comments = (
        b"Object = IsisCube\n"
        b"  Group = Dimensions\n"
        b"    Samples = 512\n"
        b"  End_Group\n"
        b"End_Object\n"
        b"End\n"
    )

    assert parse_pvl_label(with_comments) == parse_pvl_label(without_comments)


def test_bare_end_object_form_is_accepted() -> None:
    """The bare `End_Object` form (no `= Name`) closes the block."""
    label = b"Object = A\n  Keyword = 1\nEnd_Object\nEnd\n"

    result = parse_pvl_label(label)

    assert result["A"]["Keyword"] == 1


def test_end_object_equals_name_form_is_accepted() -> None:
    """The `End_Object = Name` form also closes the block."""
    label = b"Object = A\n  Keyword = 1\nEnd_Object = A\nEnd\n"

    result = parse_pvl_label(label)

    assert result["A"]["Keyword"] == 1


def test_bare_end_group_form_is_accepted() -> None:
    """The bare `End_Group` form (no `= Name`) closes the block."""
    label = b"Group = A\n  Keyword = 1\nEnd_Group\nEnd\n"

    result = parse_pvl_label(label)

    assert result["A"]["Keyword"] == 1


def test_end_group_equals_name_form_is_accepted() -> None:
    """The `End_Group = Name` form also closes the block."""
    label = b"Group = A\n  Keyword = 1\nEnd_Group = A\nEnd\n"

    result = parse_pvl_label(label)

    assert result["A"]["Keyword"] == 1


def test_limits_are_configurable_not_hardcoded() -> None:
    """A tighter `max_depth` (2) rejects a label the default limits accept."""
    label = b"Object = A\n  Object = B\n    Keyword = 1\n  End_Object\nEnd_Object\nEnd\n"  # depth 2

    # Passes under the generous default limits.
    result = parse_pvl_label(label)
    assert result["A"]["B"]["Keyword"] == 1

    # The same document is rejected once max_depth is tightened below 2.
    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label, limits=PvlParseLimits(max_depth=1))

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED


# --------------------------------------------------------------------------
# Additional fixtures (beyond the brief's minimum list) — targeted checks
# for specific grammar/limit behaviours that are easy to get subtly wrong.
# --------------------------------------------------------------------------


def test_structural_keywords_are_case_insensitive() -> None:
    """`object`/`OBJECT`/`Object`, and the matching end forms, are all
    recognised as the structural keyword, per ISIS/PDS convention — only
    the structural keywords are case-insensitive, not ordinary keywords or
    values (verified by `test_ordinary_keywords_and_values_are_case_sensitive`).
    """
    label = b"object = A\n  keyword = 1\nend_object\nEND\n"

    result = parse_pvl_label(label)

    assert result["A"]["keyword"] == 1


def test_ordinary_keywords_and_values_are_case_sensitive() -> None:
    """Two differently-cased ordinary keywords are distinct entries, and a
    symbol value's case is preserved exactly as written.
    """
    label = b"Keyword = Value\nkeyword = value\nEnd\n"

    result = parse_pvl_label(label)

    assert result["Keyword"] == "Value"
    assert result["keyword"] == "value"


def test_end_object_closing_a_group_is_rejected() -> None:
    """`End_Object` closing a block opened with `Group =` is a block-type
    mismatch, rejected under this module's stated simple rule (see module
    docstring): `End_Object` must close an `Object`, `End_Group` must close
    a `Group`.
    """
    label = b"Group = A\n  Keyword = 1\nEnd_Object\nEnd\n"

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE


def test_empty_sequence_and_set_parse_to_empty_lists() -> None:
    """`()` and `{}` are valid, empty sequences/sets."""
    label = b"Seq = ()\nSet = {}\nEnd\n"

    result = parse_pvl_label(label)

    assert result["Seq"] == []
    assert result["Set"] == []


def test_nested_sequence_is_rejected_as_unparseable() -> None:
    """Nested sequences are outside this limited-subset grammar (documented
    scope limitation, not a security rejection — see module docstring).
    """
    label = b"Keyword = (1, (2, 3))\nEnd\n"

    with pytest.raises(PvlParseError) as excinfo:
        parse_pvl_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE
