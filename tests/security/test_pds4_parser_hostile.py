"""Hostile-input fixture suite for the PDS4 label parser (WP-02 task 12).

Every fixture below is literal bytes constructed in this file — none are
downloaded or read from an external file, so the suite exercises exactly the
attack shape it claims to and nothing environment-dependent.

Each test also documents, in a comment, which defense layer in
`selene_core.ingest.pds4` is expected to catch it:

* layer 1a — the raw `<!DOCTYPE` scan (the primary defense: every
  entity-based attack needs a DOCTYPE to define custom entities or an
  external subset).
* layer 1b — the raw `<!ENTITY` scan (defense-in-depth for an entity
  declaration that manages to appear outside what looks like a DOCTYPE
  block).
* layer 2 — the during-parse `TreeBuilder` depth/element/attribute budget.

(There is no longer a bare URL/`SYSTEM`/`PUBLIC` scan: it collided with
legitimate PDS4 content — a label's own `xsi:schemaLocation` URL, or
ordinary prose like "Solar System" — and was removed once it was verified
that `SYSTEM`/`PUBLIC` only carry XML significance inside a DOCTYPE's
`ExternalID` production, which is unreachable once DOCTYPE is rejected. See
`test_schema_location_url_without_doctype_parses_successfully` below, which
guards against reintroducing that over-rejection.)
* the raw-size cap, which runs before any of the above.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import pytest

from selene_core.ingest.pds4 import Pds4ParseError, Pds4ParseLimits, parse_pds4_label
from selene_core.pipeline.failures import FailureCode

pytestmark = pytest.mark.security


# --------------------------------------------------------------------------
# Required fixtures (task brief)
# --------------------------------------------------------------------------


def test_xxe_external_entity_is_rejected_before_any_file_access() -> None:
    """layer 1a: a classic XXE payload is rejected by the DOCTYPE scan.

    The parser never reaches expat, so the `&xxe;` reference is never
    resolved and `file:///etc/passwd` is never opened — proving the parser
    raises before doing anything with the entity is sufficient; there is no
    later stage that could still act on it, because rejection happens before
    any parser exists.
    """
    label = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        b"<foo><val>&xxe;</val></foo>"
    )

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_HOSTILE_LABEL
    assert "DOCTYPE" in excinfo.value.message


def test_billion_laughs_entity_expansion_is_rejected_fast() -> None:
    """layer 1a: classic exponential entity-expansion bomb, rejected fast.

    Asserts the whole call completes well under a second, proving rejection
    happens before any entity is ever expanded (the DOCTYPE scan runs before
    expat ever sees the bytes) rather than the parser hanging and eventually
    failing.
    """
    entities = ['<!ENTITY lol "lol">']
    previous = "lol"
    for i in range(1, 10):
        current = f"lol{i}"
        entities.append(f'<!ENTITY {current} "{("&" + previous + ";") * 10}">')
        previous = current
    doctype = "<!DOCTYPE lolz [\n" + "\n".join(entities) + "\n]>"
    label = ('<?xml version="1.0"?>\n' + doctype + "\n<lolz>&lol9;</lolz>").encode()

    started = time.perf_counter()
    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)
    elapsed = time.perf_counter() - started

    assert excinfo.value.code is FailureCode.INPUT_HOSTILE_LABEL
    assert elapsed < 1.0


def test_external_dtd_reference_without_inline_entities_is_rejected() -> None:
    """layer 1a specifically: a DOCTYPE with no `<!ENTITY>` at all.

    Proves the scan catches the DOCTYPE declaration itself, not merely the
    word `ENTITY` — this document contains no entity declaration whatsoever.
    """
    label = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE foo SYSTEM "http://attacker.invalid/evil.dtd">\n'
        b"<foo>text</foo>"
    )

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_HOSTILE_LABEL
    assert "DOCTYPE" in excinfo.value.message


def test_deeply_nested_elements_without_any_doctype_hits_depth_limit() -> None:
    """layer 2 specifically: no DOCTYPE, no entities — pure structural depth.

    This input has no DOCTYPE at all, so layer 1 has nothing to reject; it
    must be caught by the depth-counting `TreeBuilder` during parsing. This
    is the proof that layer 2's during-parse limit actually works, not just
    layer 1's rejection.
    """
    label = ("<a>" * 10_000 + "x" + "</a>" * 10_000).encode()

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "depth" in excinfo.value.message.lower()


def test_wide_sibling_count_hits_element_limit() -> None:
    """layer 2 specifically: flat, not deep — 200,000 sibling elements.

    No DOCTYPE, depth stays at 2 throughout, so only the during-parse
    element-count budget can catch this.
    """
    label = b"<root>" + (b"<c/>" * 200_000) + b"</root>"

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "element count" in excinfo.value.message.lower()


def test_excessive_attributes_on_one_element_hits_attribute_limit() -> None:
    """layer 2 specifically: one element with far more than the attribute cap."""
    attrs = " ".join(f'a{i}="v"' for i in range(400))
    label = f"<root {attrs}/>".encode()

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "attributes" in excinfo.value.message.lower()


def test_oversized_input_is_rejected_before_any_scanning_or_parsing() -> None:
    """the raw-size cap: rejected fast, before the (expensive) DOCTYPE scan
    or parse would run.

    Uses a document that would be extremely expensive to actually parse (4
    million opening tags, well over the default `max_bytes`) and asserts the
    whole call still completes quickly — proof the size check runs first and
    does no other work on the oversized input.
    """
    label = ("<a>" * 4_000_000).encode()  # >10 MiB, would be very slow to parse
    assert len(label) > Pds4ParseLimits().max_bytes

    started = time.perf_counter()
    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)
    elapsed = time.perf_counter() - started

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    assert "bytes" in excinfo.value.message.lower()
    assert elapsed < 1.0


def test_path_traversal_shaped_text_content_parses_as_ordinary_text() -> None:
    """The parser does not interpret field semantics, positively or
    negatively.

    A `../../etc/passwd`-shaped string in an element body is not a hostile
    pattern by any of this module's checks (no DOCTYPE, no entity) and is
    not given any special treatment — it round-trips as plain text.
    Validating path-like fields is a later payload-adapter task's job, not
    this parser's.
    """
    label = (
        b'<?xml version="1.0"?>\n'
        b"<synthetic_test_label>"
        b"<file_reference>../../etc/passwd</file_reference>"
        b"</synthetic_test_label>"
    )

    root = parse_pds4_label(label)

    element = root.find("file_reference")
    assert element is not None
    assert element.text == "../../etc/passwd"


def test_synthetic_permitted_label_parses_successfully() -> None:
    """A well-formed, reasonable-looking label parses cleanly.

    This is a synthetic test fixture invented for this suite, not an
    instance of the real PDS4 product-observational schema (no schema is
    available in this environment) — it exists only to prove ordinary,
    non-hostile input is accepted and its structure is preserved.
    """
    label = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b"<synthetic_test_label>"
        b"<identification_area>"
        b"<product_id>synthetic-0001</product_id>"
        b"<title>Synthetic fixture for parser tests</title>"
        b"</identification_area>"
        b"<observation_area>"
        b"<instrument_name>Synthetic Camera</instrument_name>"
        b"</observation_area>"
        b"</synthetic_test_label>"
    )

    root = parse_pds4_label(label)

    assert root.tag == "synthetic_test_label"
    product_id = root.find("identification_area/product_id")
    assert product_id is not None
    assert product_id.text == "synthetic-0001"
    instrument_name = root.find("observation_area/instrument_name")
    assert instrument_name is not None
    assert instrument_name.text == "Synthetic Camera"


def test_limits_are_configurable_not_hardcoded() -> None:
    """A tighter `max_depth` rejects a document the defaults would accept.

    Proves the limit dataclass field is actually read by the parser, not a
    hardcoded constant the constructor argument is silently ignored in
    favour of.
    """
    label = b"<a><b><c><d>x</d></c></b></a>"  # depth 4

    # Passes under the generous default limits.
    root = parse_pds4_label(label)
    assert root.tag == "a"

    # The same document is rejected once max_depth is tightened below 4.
    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label, limits=Pds4ParseLimits(max_depth=3))

    assert excinfo.value.code is FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED


# --------------------------------------------------------------------------
# Additional layer-isolation fixtures (beyond the brief's minimum list) —
# each proves one defense-in-depth layer catches an attack shape the other
# layers would not.
# --------------------------------------------------------------------------


def test_entity_declaration_outside_doctype_is_still_rejected() -> None:
    """layer 1b in isolation: a `<!ENTITY` sequence with no `<!DOCTYPE`
    sequence at all.

    Not a well-formed way to declare an entity, and not achievable through
    ordinary means — but this module scans raw bytes, not a decoded
    document, precisely so that a malformed or unexpected framing cannot
    smuggle an entity declaration past the DOCTYPE-only check.
    """
    label = b'<foo><!ENTITY xxe "smuggled"><val>x</val></foo>'

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_HOSTILE_LABEL
    assert "ENTITY" in excinfo.value.message


def test_schema_location_url_without_doctype_parses_successfully() -> None:
    """Regression guard: a normal `xsi:schemaLocation` URL is not hostile.

    An earlier version of this module scanned for bare `http://`/`https://`/
    `SYSTEM`/`PUBLIC` markers anywhere in the raw bytes as defense-in-depth,
    and that scan rejected this exact, entirely ordinary PDS4 pattern — a
    label's own schema reference. It was removed because `SYSTEM`/`PUBLIC`
    only carry XML significance inside a DOCTYPE's `ExternalID` production
    (XML 1.0 grammar), which this document does not have and which is
    unreachable anyway once a DOCTYPE is rejected; a bare-keyword scan was
    therefore pure false-positive risk with no matching attack surface. This
    test parses successfully and would fail loudly if that scan were ever
    reintroduced.
    """
    label = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<synthetic_test_label xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'xsi:schemaLocation="https://pds.nasa.gov/pds4/pds/v1 '
        b'https://pds.nasa.gov/pds4/pds/v1/PDS4_PDS_1900.xsd">'
        b"<title>Solar System survey, Global Positioning System reference frame</title>"
        b"</synthetic_test_label>"
    )

    root = parse_pds4_label(label)

    assert root.tag == "synthetic_test_label"
    title = root.find("title")
    assert title is not None
    assert title.text == "Solar System survey, Global Positioning System reference frame"


def test_element_tree_parse_error_maps_to_unparseable_code() -> None:
    """Genuinely malformed XML that is not hostile by any check above still
    reaches the parser, and the parser's own `ParseError` is translated to
    `FailureCode.INPUT_LABEL_UNPARSEABLE` rather than left as a raw
    `xml.etree.ElementTree.ParseError` or misreported as hostile input.
    """
    label = b"<a><b></a>"  # mismatched tag, no DOCTYPE/entity markers

    with pytest.raises(Pds4ParseError) as excinfo:
        parse_pds4_label(label)

    assert excinfo.value.code is FailureCode.INPUT_LABEL_UNPARSEABLE


def test_depth_limit_is_enforced_during_parsing_not_after_full_materialization() -> None:
    """Directly demonstrates layer 2 interrupts the parse partway through.

    Uses `xml.etree.ElementTree.XMLParser` with the same `TreeBuilder`
    machinery `parse_pds4_label` uses internally, feeding a document 10,000
    layers deep with a `max_depth` of 64, and asserts the builder's own
    depth counter never exceeded `max_depth + 1` — proving the exception was
    raised on the 65th `start()` call, not after all 10,000 opening tags had
    already been processed and a full tree built.
    """
    from selene_core.ingest.pds4 import _LimitEnforcingTreeBuilder

    limits = Pds4ParseLimits(max_depth=64)
    builder = _LimitEnforcingTreeBuilder(limits)
    # Same hardened construction as `parse_pds4_label`: `builder` enforces the
    # depth limit during this call, which is exactly what this test verifies.
    parser = ET.XMLParser(target=builder)  # noqa: S314
    label = ("<a>" * 10_000 + "x" + "</a>" * 10_000).encode()

    with pytest.raises(Pds4ParseError):
        parser.feed(label)

    assert builder._depth == limits.max_depth + 1
