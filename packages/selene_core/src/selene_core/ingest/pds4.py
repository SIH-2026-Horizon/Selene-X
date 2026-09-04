"""Hardened PDS4 XML label parsing (WP-02 task 2).

A PDS4 label is untrusted input: it arrives from a data provider this
pipeline does not control, and it is XML, which means it inherits every
attack XML is known for — entity expansion ("billion laughs"), external
entity resolution (XXE), and plain resource exhaustion via depth or
cardinality. `selene_core` is deliberately dependency-light (ADR-005) and
`defusedxml` is not installed, so this module hardens the stdlib
`xml.etree.ElementTree` parser directly rather than adding a dependency.

The defense has two independent layers, applied in this order:

1. **A lexical pre-scan of the raw bytes, before any parser sees them.**
   Every entity-based attack (XXE, billion-laughs, external DTD fetches)
   requires a ``<!DOCTYPE`` declaration to define custom entities or point
   at an external subset. PDS4 labels reference their schema through
   ``xsi:schemaLocation`` attributes, never a DTD, so a label has no
   legitimate reason to declare one. **Rejecting any ``<!DOCTYPE`` before
   parsing eliminates the entire entity-attack class at its root** — it does
   not matter what the entity does if it is never defined. This is the
   primary defense and is verified directly by
   ``tests/security/test_pds4_parser_hostile.py``.

   One cheap defense-in-depth check rides along: a raw ``<!ENTITY`` scan, in
   case some malformed encoding smuggles an entity declaration outside what
   a naive DOCTYPE scan recognises as a DOCTYPE block. It is not a
   substitute for the DOCTYPE rejection; it is unconditional and does not
   try to distinguish a "safe" use from a hostile one, because there is no
   legitimate use of a bare ``<!ENTITY`` in this project's scope.

   An earlier version of this module also scanned for bare
   ``SYSTEM``/``PUBLIC``/``file://``/``http://``/``https://``/``ftp://``
   markers anywhere in the bytes, as further defense-in-depth. That check
   was removed: per the XML 1.0 grammar, the ``ExternalID`` production
   (where ``SYSTEM``/``PUBLIC`` carry meaning) is only reachable from
   ``doctypedecl`` or a declaration inside a DOCTYPE's internal subset, so
   once a DOCTYPE is unconditionally rejected — which it already is, and
   is independently verified sufficient against XXE and entity-expansion
   in ``tests/security/test_pds4_parser_hostile.py`` — those keywords carry
   zero further significance anywhere else in the document. Meanwhile the
   bare-keyword scan collided with ordinary legitimate PDS4 content: a
   label's own ``xsi:schemaLocation`` attribute conventionally *is* an
   ``https://`` URL, and prose fields (``<description>``, ``<title>``,
   ``Internal_Reference``) can legitimately contain "Solar System", "Global
   Positioning System", or a DOI ``https://`` citation. Removing the check
   closes a real false-positive-rejection bug without reopening any attack
   surface, since expat never reaches the ``ExternalID`` grammar production
   without a DOCTYPE regardless.

2. **A depth/element/attribute budget enforced *during* parsing**, for the
   attack class that needs no DOCTYPE at all: a document that is simply too
   deep or too wide. This is done with a custom
   `xml.etree.ElementTree.TreeBuilder` passed as the parser's `target`, so
   the budget is checked on every `start()` call as elements are produced,
   not after `ET.fromstring()` has already built (and paid for) the whole
   tree. A verified fact about this repository's Python (3.12): an
   `XMLParser` does not expose a public attribute for reaching expat's
   `StartDoctypeDeclHandler`/`ExternalEntityRefHandler` directly, so this
   module does not attempt that route; the `TreeBuilder` target is the
   supported, version-stable way to observe and interrupt a parse in
   progress.

Both layers only ever produce three failure identities, on purpose, so a
caller can build a `selene_core.pipeline.results.StageFailure` from
whichever one was raised: `FailureCode.INPUT_HOSTILE_LABEL` (layer 1, or an
adversarial input that layer 2 also happens to reject),
`FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED` (layer 2, or the raw-size cap),
and `FailureCode.INPUT_LABEL_UNPARSEABLE` (the input is not hostile by any
check above, simply not well-formed XML).

This module does not interpret PDS4 semantics. It returns a generic
`xml.etree.ElementTree.Element` tree; extracting product IDs, payload
family, or any other PDS4-specific field is payload-adapter work for a later
task.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from selene_core.errors import FailureCode

__all__ = [
    "Pds4ParseError",
    "Pds4ParseLimits",
    "parse_pds4_label",
]


@dataclass(frozen=True, slots=True)
class Pds4ParseLimits:
    """Configurable resource budget for one label parse.

    Defaults are chosen against what a legitimate PDS4 label actually looks
    like — metadata, not imagery, normally tens of KB — with generous
    headroom, not against what is theoretically possible:

    * ``max_bytes`` (10 MiB): a real label is orders of magnitude smaller;
      10 MiB comfortably covers an unusually large or verbose label while
      still capping the cost of the pre-scan and the parse itself.
    * ``max_depth`` (64): PDS4's own XML schema nests only a few levels
      deep (identification area, observation area, and a handful of
      sub-blocks); 64 leaves headroom for schema evolution without
      allowing thousands of levels of adversarial nesting.
    * ``max_elements`` (100,000): enough for a label with a large but
      legitimate structured table description; far below what a
      deliberately wide bomb would use to exhaust memory.
    * ``max_attributes_per_element`` (256): PDS4 elements typically carry a
      handful of namespace and unit attributes; 256 is generous headroom
      against a single element weaponised with an enormous attribute list.

    Every limit is enforced; the exact numbers matter less than that each
    one exists and is checked (task brief). Callers may construct a
    narrower or wider instance for a specific route's needs.
    """

    max_bytes: int = 10 * 1024 * 1024
    max_depth: int = 64
    max_elements: int = 100_000
    max_attributes_per_element: int = 256


class Pds4ParseError(Exception):
    """A PDS4 label was rejected, or could not be parsed.

    Carries a stable `FailureCode` rather than requiring the caller to
    infer one from a message string, so a caller assembling a
    `selene_core.pipeline.results.StageFailure` (or any other reporting
    contract) never has to re-derive what kind of failure this was. A
    full `StageFailure` is not built here: this module has no opinion on
    stage identity, retry bookkeeping, or provenance, all of which
    `StageFailure` requires and a caller is better placed to supply.
    """

    def __init__(self, code: FailureCode, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context: dict[str, Any] = dict(context)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Pds4ParseError(code={self.code!r}, message={self.message!r})"


# Case-insensitive, tolerant of whitespace between "<!" and the keyword, since
# an attacker is not obliged to write the sequence the way a well-formed
# document would. Matched against raw bytes, never a decoded/parsed
# structure, so the scan cannot itself be fooled by something a parser would
# have normalised away.
_DOCTYPE_PATTERN = re.compile(rb"<!\s*DOCTYPE", re.IGNORECASE)
_ENTITY_PATTERN = re.compile(rb"<!\s*ENTITY", re.IGNORECASE)


def _reject_hostile_bytes(data: bytes, limits: Pds4ParseLimits) -> None:
    """Layer 1: reject on raw bytes, before any parser runs.

    Order matters. The size check runs first and does no other work, so an
    oversized input is rejected without the cost of scanning or decoding it.
    The DOCTYPE scan is the primary defense; the entity scan is cheap
    defense-in-depth layered on top, not a substitute for it. There is
    deliberately no scan for bare URL/SYSTEM/PUBLIC markers: those keywords
    only carry XML significance inside a DOCTYPE's ``ExternalID``
    production, which is unreachable once a DOCTYPE is rejected, and a
    bare-keyword scan collided with legitimate content (a label's own
    ``xsi:schemaLocation`` URL, or ordinary prose like "Solar System").
    """
    if len(data) > limits.max_bytes:
        raise Pds4ParseError(
            FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
            f"label is {len(data)} bytes, exceeding the {limits.max_bytes}-byte limit",
            size_bytes=len(data),
            max_bytes=limits.max_bytes,
        )

    if _DOCTYPE_PATTERN.search(data) is not None:
        raise Pds4ParseError(
            FailureCode.INPUT_HOSTILE_LABEL,
            "label declares a DOCTYPE; PDS4 labels reference their schema via "
            "xsi:schemaLocation and have no legitimate reason to declare one",
        )

    if _ENTITY_PATTERN.search(data) is not None:
        raise Pds4ParseError(
            FailureCode.INPUT_HOSTILE_LABEL,
            "label contains an ENTITY declaration outside a recognised DOCTYPE block",
        )


class _LimitEnforcingTreeBuilder(ET.TreeBuilder):
    """Enforces depth/element/attribute budgets as elements are produced.

    `xml.etree.ElementTree.XMLParser` calls `start()` once per opening tag
    and `end()` once per closing tag, in document order, as bytes are fed to
    it — well before the whole document has been read. Raising out of
    `start()` here propagates straight out of `XMLParser.feed()`/`.close()`
    (verified directly against this repository's Python 3.12; expat does not
    catch or wrap a handler's exception), which is what makes this a
    *during-parse* limit: a document that is 100,000 elements deep is
    stopped at element 100,001, never fully materialised.
    """

    def __init__(self, limits: Pds4ParseLimits) -> None:
        super().__init__()
        self._limits = limits
        self._depth = 0
        self._element_count = 0

    def start(self, tag: str, attrib: dict[str, str]) -> Any:
        self._depth += 1
        if self._depth > self._limits.max_depth:
            raise Pds4ParseError(
                FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                f"element nesting depth {self._depth} exceeds max_depth={self._limits.max_depth}",
                depth=self._depth,
                max_depth=self._limits.max_depth,
            )

        self._element_count += 1
        if self._element_count > self._limits.max_elements:
            raise Pds4ParseError(
                FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                f"element count {self._element_count} exceeds max_elements="
                f"{self._limits.max_elements}",
                element_count=self._element_count,
                max_elements=self._limits.max_elements,
            )

        if len(attrib) > self._limits.max_attributes_per_element:
            raise Pds4ParseError(
                FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                f"element <{tag}> has {len(attrib)} attributes, exceeding "
                f"max_attributes_per_element={self._limits.max_attributes_per_element}",
                tag=tag,
                attribute_count=len(attrib),
                max_attributes_per_element=self._limits.max_attributes_per_element,
            )

        return super().start(tag, attrib)

    def end(self, tag: str) -> Any:
        self._depth -= 1
        return super().end(tag)


def parse_pds4_label(data: bytes, *, limits: Pds4ParseLimits | None = None) -> ET.Element:
    """Parse a PDS4 XML label under a hostile-input threat model.

    Runs, in order: the raw-size cap, the DOCTYPE/entity pre-scan (layer 1),
    then a parse with `xml.etree.ElementTree` under a
    depth/element/attribute budget enforced during parsing (layer 2).
    `xml.etree.ElementTree` is only ever invoked after the input has passed
    layer 1 — the entity-based attack classes layer 1 exists to stop are
    never given a parser to run against in the first place.

    Args:
        data: The raw label bytes, exactly as read from the source. Not a
            path: this function never touches the filesystem, so it has no
            opinion on where the bytes came from.
        limits: Overrides for `Pds4ParseLimits`. Defaults to
            `Pds4ParseLimits()` when omitted.

    Returns:
        The parsed root `xml.etree.ElementTree.Element`. No PDS4 semantics
        are interpreted; this is a generic element tree.

    Raises:
        Pds4ParseError: with `FailureCode.INPUT_HOSTILE_LABEL` if the raw
            bytes match a hostile pattern; `FailureCode
            .INPUT_RESOURCE_LIMIT_EXCEEDED` if the raw size or an
            during-parse depth/element/attribute budget is exceeded;
            `FailureCode.INPUT_LABEL_UNPARSEABLE` if the input clears every
            hostile-pattern and resource check but is not well-formed XML.
    """
    limits = limits if limits is not None else Pds4ParseLimits()

    _reject_hostile_bytes(data, limits)

    builder = _LimitEnforcingTreeBuilder(limits)
    # `defusedxml` is not installed (ADR-005: selene_core stays dependency-light) and
    # this whole module exists to harden stdlib ElementTree in its place — see the
    # module docstring for the two-layer defense that makes this use of `XMLParser`
    # safe against untrusted input: `data` has already passed the DOCTYPE/entity
    # pre-scan above, and `builder` enforces depth/element/attribute limits during
    # this call.
    parser = ET.XMLParser(target=builder)  # noqa: S314
    try:
        parser.feed(data)
        root = parser.close()
    except Pds4ParseError:
        # Raised by the TreeBuilder above; already the right shape.
        raise
    except ET.ParseError as exc:
        raise Pds4ParseError(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            f"label is not well-formed XML: {exc}",
        ) from exc

    return root
