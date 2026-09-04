"""A hardened, limited-subset ISIS/PVL label parser (WP-02 task 3).

An ISIS cube or PDS3 label is untrusted input, exactly like the PDS4 XML
label handled by `selene_core.ingest.pds4`, but PVL (Parameter Value
Language) is a much simpler format than XML: **it has no entity-expansion or
external-DTD mechanism**. There is no PVL analog of XXE or "billion laughs" —
nothing in the grammar lets one label statement expand into another, and
there is no construct that causes a compliant reader to fetch or open
anything. That is a fact about the format, not an assumption this module
relies on without checking: the grammar below (see "Grammar subset
supported") has no expansion or inclusion construct of any kind.

The resource-exhaustion risks that *do* exist for PVL are purely structural,
and this module defends against exactly those, and nothing else:

* **Deeply nested `Object`/`Group` blocks** — a stack-depth/recursion bomb.
  Defended by `PvlParseLimits.max_depth`, enforced by an explicit `list`-based
  stack in `_parse_statements`, never by Python function recursion — the same
  reason `pds4._LimitEnforcingTreeBuilder` avoids recursion: a maliciously
  deep label must be caught by this module's own counter and rejected
  cleanly with `FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED`, not allowed to
  raise a raw `RecursionError`.
* **A very large sequence or set value** (`(a, b, c, ...)` / `{a, b, c,
  ...}`) — defended by `PvlParseLimits.max_sequence_items`, checked as each
  element is appended, not after the whole sequence has been built.
* **A very large number of top-level statements** — defended by
  `PvlParseLimits.max_statements`, incremented and checked the instant a
  statement is recognised, before its value is parsed.
* **Plain oversized input** — defended by `PvlParseLimits.max_bytes`,
  checked first, before any decoding or tokenizing.

**`^POINTER_NAME = value` statements are not a special case and are not
treated with suspicion.** PVL's caret-prefixed keyword syntax (e.g.
``^IMAGE = ("cube.img", 65)``) is a normal, safe feature: it names an
external file that carries attached binary data alongside the label. This
parser handles it exactly like any other `Keyword = Value` statement — the
caret is just a character in the keyword name — and extracts the pointer's
value as a literal string/sequence, the same as it would any other value.
**This module never opens, reads, or stats any file, regardless of what a
label's content says**; that is the correct security boundary here, not
scanning pointer values for what they look like. `pds4.py`'s module
docstring records a case where an earlier defense-in-depth check
(scanning for bare ``SYSTEM``/``PUBLIC``/``file://`` markers) was removed
because it rejected legitimate content that merely *looked* suspicious
without being reachable by any actual attack; this module deliberately does
not repeat that mistake by inventing a PVL analog of that check. There is no
`FailureCode.INPUT_HOSTILE_LABEL` case produced anywhere in this module for
that reason — every rejection here is either a resource-limit rejection or a
malformed-syntax rejection, both independently justified above and in the
grammar notes below.

## Limited-subset disclaimer

The `pvl` package is not installed in this environment (ADR-005:
`selene_core` stays dependency-light), so this module is a purpose-built
tokenizer/parser sufficient for **label validation** — extracting
keyword/value pairs and nested `Object`/`Group` structure under strict
size/depth/count limits — not a complete, spec-faithful PVL/ODL
implementation. Stated plainly, the same way this codebase states IIRS's
incomplete geometry status honestly elsewhere (see `GEOMETRY_MODEL_UNVALIDATED`
in `selene_core.pipeline.failures`): this parser does not implement the full
PVL/ODL grammar, and callers needing full spec fidelity should not assume it.

## Grammar subset supported

* `Keyword = Value` statements. `End`, `Object`, `Group`, `End_Object`, and
  `End_Group` are recognised case-insensitively (per ISIS/PDS convention);
  every other keyword and every value is case-sensitive.
* Block structure: ``Object = Name`` ... ``End_Object`` and
  ``Group = Name`` ... ``End_Group``, closed by either the bare
  ``End_Object``/``End_Group`` form or the ``End_Object = Name`` /
  ``End_Group = Name`` form (both are legal PVL; the optional ``= Name`` is
  parsed and discarded without checking it matches the opening name — a
  deliberate simplification, not a security concern). A bare ``End``
  terminates the whole label; running out of input without ever seeing one
  also terminates the label leniently (no error), since some real-world PVL
  omits a trailing ``End``.
* A simple, stated rule for mismatched closes: ``End_Object`` must close a
  block that was opened with ``Object =``, and ``End_Group`` must close one
  opened with ``Group =``; a mismatch is rejected as
  `FailureCode.INPUT_LABEL_UNPARSEABLE`. ISIS itself is more lenient about
  this in practice; this module is not required to replicate every
  real-world leniency, and a stated, simple rule is sufficient here.
* Values: quoted strings (`"..."` and `'...'`), unquoted symbols/identifiers,
  integers, floats, and PVL's ``NUMBER <UNIT>`` form (e.g. ``10.5 <km>``),
  sequences (`(a, b, c)`), and sets (`{a, b, c}`).
* Comments: ``/* ... */`` (block, non-nesting, per PVL/ODL — the first
  ``*/`` closes it) and ``#`` to end of line. Comments are stripped during
  tokenizing and never appear in the parsed structure.
* ``^POINTER_NAME = value`` — the caret is simply part of the keyword text;
  see above.

What this grammar subset deliberately does **not** support, and rejects as
`FailureCode.INPUT_LABEL_UNPARSEABLE` malformed syntax if encountered (not
because any of these are dangerous, only because implementing them is out of
scope for a label-validation reader):

* Backslash escape sequences inside quoted strings. A string ends at the
  first occurrence of its own opening quote character; it cannot contain
  that character. Multi-line strings (a literal newline before the closing
  quote) are accepted, matching real ISIS label content.
* Nested sequences/sets (e.g. ``(1, (2, 3))``). Only scalar elements
  (strings, symbols, numbers) are accepted inside a `(...)`/`{...}`.
* Radix-prefixed numbers (PVL's ``2#1010#`` based-integer form) and other
  ODL numeric literal forms beyond plain decimal integers/floats and
  ``NUMBER <UNIT>``.
* Any keyword or value token containing characters outside
  ``[A-Za-z0-9_:^-]`` for identifiers — such a byte sequence is rejected as
  an unrecognised character, not interpreted.

A numeric value with a unit (``10.5 <km>``) is captured as a `PvlQuantity`,
preserving both parts, rather than discarding the unit or merging it into
the number — a caller validating a scale or distance field needs the unit to
interpret the number correctly.

A top-level ``Object = IsisCube`` wrapping the whole label — the normal ISIS
cube shape — requires no special handling: it becomes an ordinary entry in
the returned dict, e.g. ``result["IsisCube"]["Instrument"]["SomeKeyword"]``.
There is nothing else at the top level of a well-formed ISIS label once that
one `Object` closes, but this module does not require or assume that shape;
a label with several top-level statements and blocks is handled the same
way.

A duplicate keyword or block name within the same container (e.g. two
``Group = Instrument`` blocks, or a repeated ``HISTORY`` keyword — both do
occur in real ISIS/PDS3 practice) is not accumulated: the later occurrence's
value silently replaces the earlier one in the returned `dict`. This is a
stated limitation of the generic nested-dict representation this module
returns, not a security concern, and not addressed further here; a payload
adapter needing every occurrence of a repeated keyword must not rely on this
module.

This module does not interpret ISIS/PDS3 semantics: values like ``YES``,
``NO``, ``TRUE``, or ``FALSE`` are returned as plain strings, not booleans.
Extracting instrument names, band metadata, or any other ISIS-specific
field is payload-adapter work for a later task.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from selene_core.errors import FailureCode

__all__ = [
    "PvlParseError",
    "PvlParseLimits",
    "PvlQuantity",
    "parse_pvl_label",
]


@dataclass(frozen=True, slots=True)
class PvlParseLimits:
    """Configurable resource budget for one label parse.

    Defaults are chosen against what a legitimate ISIS/PDS3 label actually
    looks like — text metadata, typically tens of KB, with modest nesting —
    with generous headroom, not against what is theoretically possible:

    * ``max_bytes`` (5 MiB): a real label is orders of magnitude smaller;
      5 MiB comfortably covers an unusually large or verbose label (a long
      processing history, for instance) while still capping the cost of
      decoding and tokenizing the input.
    * ``max_depth`` (16): a handful of `Group` levels inside one top-level
      `Object` (the normal ISIS cube shape, e.g. ``IsisCube`` containing
      ``Group = Instrument``, ``Group = BandBin``, and similar siblings) is
      normal; 16 leaves headroom for unusually structured labels without
      allowing thousands of levels of adversarial nesting.
    * ``max_statements`` (10,000): a real label has on the order of a few
      hundred keyword/block statements even with an extensive processing
      history; 10,000 is generous headroom, far below what a deliberately
      wide bomb of ``Keyword_N = value`` statements would use.
    * ``max_sequence_items`` (10,000): real ISIS sequences (band-center
      wavelengths, histogram bins) run to at most low thousands of
      elements; 10,000 comfortably covers that while remaining far below
      what a single adversarial ``(1, 2, 3, ..., N)`` value would use to
      exhaust memory.

    Every limit is enforced; the exact numbers matter less than that each
    one exists and is checked during parsing. Callers may construct a
    narrower or wider instance for a specific route's needs.
    """

    max_bytes: int = 5 * 1024 * 1024
    max_depth: int = 16
    max_statements: int = 10_000
    max_sequence_items: int = 10_000


@dataclass(frozen=True, slots=True)
class PvlQuantity:
    """A numeric PVL value carrying a unit, e.g. ``10.5 <km>``.

    PVL's ``NUMBER <UNIT>`` form pairs a bare number with a unit written in
    angle brackets immediately after it. This parser preserves both parts
    rather than discarding the unit or silently folding it into the number,
    since a caller validating a scale or distance field needs the unit to
    interpret ``value`` correctly.
    """

    value: int | float
    unit: str


class PvlParseError(Exception):
    """A PVL label was rejected, or could not be parsed.

    Carries a stable `FailureCode` rather than requiring the caller to infer
    one from a message string, mirroring `selene_core.ingest.pds4
    .Pds4ParseError`. Only two codes are ever raised by this module —
    `FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED` and
    `FailureCode.INPUT_LABEL_UNPARSEABLE` — see the module docstring for why
    `FailureCode.INPUT_HOSTILE_LABEL` has no case here.
    """

    def __init__(self, code: FailureCode, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context: dict[str, Any] = dict(context)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"PvlParseError(code={self.code!r}, message={self.message!r})"


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class _TokenKind(Enum):
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    EQUALS = auto()
    SEQ_OPEN = auto()
    SEQ_CLOSE = auto()
    SET_OPEN = auto()
    SET_CLOSE = auto()
    COMMA = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class _Token:
    kind: _TokenKind
    value: Any = None


_IDENT_START = re.compile(r"[A-Za-z_^]")
_IDENT_CONTINUE = re.compile(r"[A-Za-z0-9_:\-]")
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


def _tokenize(text: str) -> Iterator[_Token]:
    """Lazily yield tokens for `text`, one at a time.

    A generator, not a function returning a fully-built list, so a parser
    consuming it (`_TokenStream`, via `_parse_statements`) never pays the
    cost of tokenizing more of a hostile document than it takes to hit
    whichever limit rejects it — the moment the parser stops calling
    `next()`, no further lexical work happens.

    Raises `PvlParseError` (`FailureCode.INPUT_LABEL_UNPARSEABLE`) directly
    for any lexical problem: an unterminated quoted string, an unterminated
    ``/* */`` comment, an unterminated ``<unit>`` bracket, or a character
    this grammar subset does not recognise. These are all malformed-syntax
    cases, never resource-exhaustion ones — the input has already passed
    the ``max_bytes`` check by the time tokenizing starts.
    """
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]

        if ch in " \t\r\n":
            i += 1
            continue

        if ch == "#":
            newline = text.find("\n", i)
            i = n if newline == -1 else newline + 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    "unterminated '/* ... */' comment",
                )
            i = end + 2
            continue

        if ch == "=":
            yield _Token(_TokenKind.EQUALS)
            i += 1
            continue
        if ch == "(":
            yield _Token(_TokenKind.SEQ_OPEN)
            i += 1
            continue
        if ch == ")":
            yield _Token(_TokenKind.SEQ_CLOSE)
            i += 1
            continue
        if ch == "{":
            yield _Token(_TokenKind.SET_OPEN)
            i += 1
            continue
        if ch == "}":
            yield _Token(_TokenKind.SET_CLOSE)
            i += 1
            continue
        if ch == ",":
            yield _Token(_TokenKind.COMMA)
            i += 1
            continue

        if ch in "\"'":
            closing = text.find(ch, i + 1)
            if closing == -1:
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    f"unterminated quoted string (no closing {ch!r} found)",
                )
            yield _Token(_TokenKind.STRING, text[i + 1 : closing])
            i = closing + 1
            continue

        if _IDENT_START.match(ch):
            j = i + 1
            while j < n and _IDENT_CONTINUE.match(text[j]):
                j += 1
            yield _Token(_TokenKind.IDENT, text[i:j])
            i = j
            continue

        number_match = _NUMBER_RE.match(text, i)
        if number_match is not None:
            literal = number_match.group(0)
            value: int | float = (
                float(literal) if ("." in literal or "e" in literal.lower()) else int(literal)
            )
            j = number_match.end()

            k = j
            while k < n and text[k] in " \t":
                k += 1
            if k < n and text[k] == "<":
                close_bracket = text.find(">", k + 1)
                if close_bracket == -1:
                    raise PvlParseError(
                        FailureCode.INPUT_LABEL_UNPARSEABLE,
                        "unterminated unit bracket ('<' with no closing '>')",
                    )
                unit = text[k + 1 : close_bracket]
                yield _Token(_TokenKind.NUMBER, PvlQuantity(value, unit))
                i = close_bracket + 1
                continue

            yield _Token(_TokenKind.NUMBER, value)
            i = j
            continue

        raise PvlParseError(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            f"unrecognized character {ch!r} at offset {i}",
        )

    yield _Token(_TokenKind.EOF)


class _TokenStream:
    """A single-token-of-pushback wrapper around the lazy tokenizer.

    Pushback is needed only to look ahead one token past
    ``End_Object``/``End_Group`` to decide whether an optional ``= Name``
    follows. Everything else is a straight pull from the generator.
    """

    def __init__(self, tokens: Iterator[_Token]) -> None:
        self._tokens = tokens
        self._pushed: _Token | None = None

    def next(self) -> _Token:
        if self._pushed is not None:
            tok = self._pushed
            self._pushed = None
            return tok
        return next(self._tokens)

    def push_back(self, token: _Token) -> None:
        self._pushed = token


# ---------------------------------------------------------------------------
# Structural parser
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Frame:
    """One open `Object`/`Group` block on the explicit parse stack."""

    block_type: str  # "OBJECT" or "GROUP"
    name: str
    contents: dict[str, Any]


def _consume_optional_end_name(stream: _TokenStream) -> None:
    """Consume an optional ``= Name`` after a bare ``End_Object``/``End_Group``.

    Both the bare form and the ``= Name`` form are legal PVL. The name, if
    present, is parsed and discarded without checking it matches the name
    the block was opened with — a deliberate simplification (see the module
    docstring), not a security concern.
    """
    lookahead = stream.next()
    if lookahead.kind is not _TokenKind.EQUALS:
        stream.push_back(lookahead)
        return

    name_tok = stream.next()
    if name_tok.kind not in (_TokenKind.IDENT, _TokenKind.STRING):
        raise PvlParseError(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            f"expected a name after End_Object=/End_Group=, found {name_tok.kind.name}",
        )


def _parse_value(stream: _TokenStream, limits: PvlParseLimits) -> Any:
    """Parse one value: a scalar, or a flat sequence/set of scalars.

    Nested sequences/sets are rejected as unparseable (see "Grammar subset
    supported" in the module docstring) — this is a scope limitation of the
    limited-subset grammar, not a resource-exhaustion defense.

    Sequence/set element count is checked *before* each element is
    appended, so a value like ``(1, 2, 3, ..., 100000)`` is rejected the
    instant it would exceed ``max_sequence_items``, never after the whole
    list has been built.
    """
    tok = stream.next()

    if tok.kind in (_TokenKind.STRING, _TokenKind.NUMBER, _TokenKind.IDENT):
        return tok.value

    if tok.kind in (_TokenKind.SEQ_OPEN, _TokenKind.SET_OPEN):
        closing = _TokenKind.SEQ_CLOSE if tok.kind is _TokenKind.SEQ_OPEN else _TokenKind.SET_CLOSE
        items: list[Any] = []

        peek = stream.next()
        if peek.kind is closing:
            return items
        stream.push_back(peek)

        while True:
            item_tok = stream.next()
            if item_tok.kind in (_TokenKind.SEQ_OPEN, _TokenKind.SET_OPEN):
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    "nested sequences/sets are not supported by this limited-subset PVL parser",
                )
            if item_tok.kind not in (_TokenKind.STRING, _TokenKind.NUMBER, _TokenKind.IDENT):
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    f"unexpected token {item_tok.kind.name} inside a sequence/set value",
                )

            if len(items) >= limits.max_sequence_items:
                raise PvlParseError(
                    FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                    f"sequence/set exceeds max_sequence_items={limits.max_sequence_items}",
                    max_sequence_items=limits.max_sequence_items,
                )
            items.append(item_tok.value)

            sep = stream.next()
            if sep.kind is closing:
                break
            if sep.kind is not _TokenKind.COMMA:
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    "expected ',' or a closing bracket in a sequence/set value, "
                    f"found {sep.kind.name}",
                )

        return items

    raise PvlParseError(
        FailureCode.INPUT_LABEL_UNPARSEABLE,
        f"expected a value, found {tok.kind.name}",
    )


def _parse_statements(stream: _TokenStream, limits: PvlParseLimits) -> dict[str, Any]:
    """Parse the whole label into a nested dict, using an explicit stack.

    This loop is the reason a maliciously deep label is caught cleanly: it
    is a flat `while` loop over `stack: list[_Frame]`, never a Python
    function calling itself, so `max_depth` is enforced by this module's own
    counter (checked *before* `stack.append(...)`) rather than allowing a
    raw `RecursionError` to propagate out of a Python call stack.

    Statement count is incremented and checked the instant a statement (a
    `Keyword = Value` assignment, or an `Object =`/`Group =` block open) is
    recognised — before its value (or, for a block, before pushing the new
    frame) is parsed — so a wide bomb of thousands of statements is rejected
    without parsing anywhere near all of them.
    """
    root: dict[str, Any] = {}
    stack: list[_Frame] = []
    statement_count = 0

    while True:
        tok = stream.next()
        if tok.kind is _TokenKind.EOF:
            break

        if tok.kind is not _TokenKind.IDENT:
            raise PvlParseError(
                FailureCode.INPUT_LABEL_UNPARSEABLE,
                f"expected a keyword, found {tok.kind.name} where a statement should start",
            )

        keyword = str(tok.value)
        upper = keyword.upper()

        if upper == "END":
            break

        if upper in ("END_OBJECT", "END_GROUP"):
            expected_type = "OBJECT" if upper == "END_OBJECT" else "GROUP"
            _consume_optional_end_name(stream)

            if not stack:
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    f"{keyword} has no matching Object/Group currently open",
                )

            frame = stack.pop()
            if frame.block_type != expected_type:
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    f"{keyword} closes a block opened as "
                    f"{frame.block_type.title()} (named {frame.name!r}); this parser "
                    "requires End_Object/End_Group to match the keyword that opened "
                    "the block",
                )

            target = stack[-1].contents if stack else root
            target[frame.name] = frame.contents
            continue

        equals_tok = stream.next()
        if equals_tok.kind is not _TokenKind.EQUALS:
            raise PvlParseError(
                FailureCode.INPUT_LABEL_UNPARSEABLE,
                f"expected '=' after keyword {keyword!r}, found {equals_tok.kind.name}",
            )

        if upper in ("OBJECT", "GROUP"):
            name_tok = stream.next()
            if name_tok.kind not in (_TokenKind.IDENT, _TokenKind.STRING):
                raise PvlParseError(
                    FailureCode.INPUT_LABEL_UNPARSEABLE,
                    f"expected a name after {keyword} =, found {name_tok.kind.name}",
                )

            statement_count += 1
            if statement_count > limits.max_statements:
                raise PvlParseError(
                    FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                    f"statement count exceeds max_statements={limits.max_statements}",
                    max_statements=limits.max_statements,
                )

            new_depth = len(stack) + 1
            if new_depth > limits.max_depth:
                raise PvlParseError(
                    FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                    f"Object/Group nesting depth {new_depth} exceeds max_depth={limits.max_depth}",
                    depth=new_depth,
                    max_depth=limits.max_depth,
                )

            stack.append(_Frame(block_type=upper, name=str(name_tok.value), contents={}))
            continue

        # An ordinary `Keyword = Value` statement (including `^POINTER = value`,
        # which is handled identically — the caret is just part of `keyword`).
        statement_count += 1
        if statement_count > limits.max_statements:
            raise PvlParseError(
                FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
                f"statement count exceeds max_statements={limits.max_statements}",
                max_statements=limits.max_statements,
            )

        value = _parse_value(stream, limits)
        target = stack[-1].contents if stack else root
        target[keyword] = value

    if stack:
        unclosed = stack[-1]
        raise PvlParseError(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            f"{unclosed.block_type.title()} {unclosed.name!r} was never closed with "
            f"End_{unclosed.block_type.title()} before the label ended",
        )

    return root


def parse_pvl_label(data: bytes, *, limits: PvlParseLimits | None = None) -> dict[str, Any]:
    """Parse an ISIS/PDS3 PVL label under a hostile-input threat model.

    Runs, in order: the raw-size cap (before any decoding or tokenizing
    happens), a UTF-8 decode, then a tokenize-and-parse pass using an
    explicit stack, with every configured limit enforced as it goes — see
    the module docstring for the full threat model and the grammar subset
    this parser supports.

    Args:
        data: The raw label bytes, exactly as read from the source. Not a
            path: this function never touches the filesystem, so it has no
            opinion on where the bytes came from, and it never opens any
            file a ``^POINTER`` value inside the label names.
        limits: Overrides for `PvlParseLimits`. Defaults to
            `PvlParseLimits()` when omitted.

    Returns:
        A nested `dict`. Plain `Keyword = Value` statements map the keyword
        to its parsed value (`str`, `int`, `float`, `PvlQuantity`, or a
        `list` for a sequence/set). `Object`/`Group` blocks map their name
        to a nested `dict` of their own contents, recursively.

    Raises:
        PvlParseError: with `FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED` if
            the raw size, nesting depth, statement count, or sequence/set
            element count exceeds a configured limit;
            `FailureCode.INPUT_LABEL_UNPARSEABLE` if the input is not
            hostile by any resource-limit check but is not well-formed PVL
            (or uses a construct outside the grammar subset this module
            supports). There is no `FailureCode.INPUT_HOSTILE_LABEL` case —
            see the module docstring for why.
    """
    limits = limits if limits is not None else PvlParseLimits()

    if len(data) > limits.max_bytes:
        raise PvlParseError(
            FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
            f"label is {len(data)} bytes, exceeding the {limits.max_bytes}-byte limit",
            size_bytes=len(data),
            max_bytes=limits.max_bytes,
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PvlParseError(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            f"label is not valid UTF-8: {exc}",
        ) from exc

    stream = _TokenStream(_tokenize(text))
    return _parse_statements(stream, limits)
