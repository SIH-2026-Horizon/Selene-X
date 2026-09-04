"""Structured logging with run, stage, and route context (WP-01 task 6).

Two requirements shape this module:

* Every record carries the identifiers needed to correlate it: run, product,
  route, stage, algorithm, and trace.
* **Imagery, tokens, credentials, and signed URLs are never logged.** That is
  not a convention to remember at each call site; it is enforced here. A record
  whose payload looks like a credential is redacted before it reaches a handler,
  and a payload that is not JSON-serialisable is summarised rather than
  stringified, so a NumPy array cannot be dumped into a log by accident.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

__all__ = [
    "REDACTED",
    "JsonLogFormatter",
    "LogContext",
    "configure_logging",
    "get_logger",
    "log_context",
]

REDACTED: Final = "[redacted]"

_SENSITIVE_KEY = re.compile(
    r"(token|secret|password|passwd|credential|api[_-]?key|authorization|signature|"
    r"signed[_-]?url|cookie|session)",
    re.IGNORECASE,
)

_SIGNED_URL = re.compile(
    r"https?://\S*(?:[?&](?:X-Amz-Signature|Signature|AWSAccessKeyId|token|sig)=)\S*",
    re.IGNORECASE,
)

_MAX_STRING_CHARS: Final = 2048
_MAX_SEQUENCE_ITEMS: Final = 64

_CONTEXT_FIELDS: Final = (
    "run_id",
    "product_id",
    "route_id",
    "stage",
    "attempt",
    "algorithm",
    "trace_id",
)


class LogContext(dict[str, Any]):
    """The identifier set attached to every record in scope."""


_context: ContextVar[LogContext | None] = ContextVar("selene_log_context", default=None)


def _current_context() -> LogContext:
    return _context.get() or LogContext()


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Attach identifiers to every log record emitted inside the block.

    Nested blocks merge, so a stage can add ``stage`` and ``attempt`` without
    knowing that a caller already set ``run_id``.
    """
    unknown = set(fields) - set(_CONTEXT_FIELDS)
    if unknown:
        raise ValueError(
            f"unknown log context field(s) {sorted(unknown)}; the correlation fields are "
            f"{list(_CONTEXT_FIELDS)}. Put anything else in the record's extra payload, where "
            "it is redaction-checked."
        )
    merged = LogContext(_current_context())
    merged.update({key: value for key, value in fields.items() if value is not None})
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def sanitise(value: Any, *, key: str | None = None) -> Any:
    """Return a log-safe version of ``value``.

    Redacts anything whose key looks like a credential, elides signed URLs,
    truncates long strings, caps sequence length, and replaces objects that are
    not JSON-serialisable with a type-and-size summary rather than their
    ``repr``. The last rule is what keeps pixel data out of logs: a NumPy array
    logs as its shape, never its contents.
    """
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        redacted = _SIGNED_URL.sub(REDACTED, value)
        if len(redacted) > _MAX_STRING_CHARS:
            return f"{redacted[:_MAX_STRING_CHARS]}... [{len(redacted)} chars]"
        return redacted
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): sanitise(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        items = list(value)
        head = [sanitise(item) for item in items[:_MAX_SEQUENCE_ITEMS]]
        if len(items) > _MAX_SEQUENCE_ITEMS:
            head.append(f"... [{len(items)} items]")
        return head
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{type(value).__name__} {len(bytes(value))} bytes>"
    return _summarise_object(value)


def _summarise_object(value: Any) -> str:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return f"<{type(value).__name__} shape={tuple(shape)!r}>"
    try:
        return f"<{type(value).__name__} len={len(value)}>"
    except TypeError:
        # No usable length. Fall through to the bare type name rather than the
        # repr, which is the whole point: an unknown object never prints itself
        # into a log.
        return f"<{type(value).__name__}>"


class JsonLogFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp_utc": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitise(record.getMessage()),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = sanitise(value, key=field)
        extra = getattr(record, "payload", None)
        if extra:
            payload["payload"] = sanitise(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _current_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class _SeleneLogger(logging.LoggerAdapter[logging.Logger]):
    """Adapter that funnels structured data through one redaction-checked field."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = dict(kwargs.get("extra") or {})
        payload = {key: value for key, value in extra.items() if key not in _CONTEXT_FIELDS}
        forwarded = {key: value for key, value in extra.items() if key in _CONTEXT_FIELDS}
        if payload:
            forwarded["payload"] = payload
        kwargs["extra"] = forwarded
        return msg, kwargs


def get_logger(name: str) -> _SeleneLogger:
    """Return a logger that carries the ambient run and stage context.

    Any keyword passed through ``extra=`` that is not a correlation field is
    moved into a ``payload`` object and sanitised, so no call site can route
    around redaction.
    """
    return _SeleneLogger(logging.getLogger(name), {})


def configure_logging(level: int = logging.INFO, *, stream: Any = None) -> None:
    """Install the JSON formatter and context filter on the root logger.

    Applications call this. Libraries never do, so importing ``selene_core``
    does not reconfigure a host application's logging.
    """
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
