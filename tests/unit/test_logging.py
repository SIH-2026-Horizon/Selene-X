"""Tests for structured logging with context and redaction.

Covers sanitise, log_context, JsonLogFormatter, get_logger, and
configure_logging.
"""

import io
import json
import logging
from collections.abc import Generator

import pytest

from selene_core.pipeline.logging import (
    REDACTED,
    JsonLogFormatter,
    _ContextFilter,
    configure_logging,
    get_logger,
    log_context,
    sanitise,
)

pytestmark = pytest.mark.unit


class TestSanitise:
    """Tests for the sanitise function."""

    def test_sanitise_redacts_api_key(self) -> None:
        """sanitise redacts values with API key-like keys."""
        result = sanitise("secret123", key="api_key")
        assert result == REDACTED

    def test_sanitise_redacts_password(self) -> None:
        """sanitise redacts values with password-like keys."""
        result = sanitise("mypassword", key="password")
        assert result == REDACTED

    def test_sanitise_redacts_token(self) -> None:
        """sanitise redacts values with token-like keys."""
        result = sanitise("token_value", key="token")
        assert result == REDACTED

    def test_sanitise_redacts_authorization(self) -> None:
        """sanitise redacts values with Authorization-like keys."""
        result = sanitise("Bearer xyz", key="Authorization")
        assert result == REDACTED

    def test_sanitise_redacts_credential(self) -> None:
        """sanitise redacts values with credential-like keys."""
        result = sanitise("cred_value", key="credential")
        assert result == REDACTED

    def test_sanitise_preserves_normal_strings(self) -> None:
        """sanitise preserves normal strings without redaction."""
        result = sanitise("normal string", key="normal_key")
        assert result == "normal string"

    def test_sanitise_truncates_long_strings(self) -> None:
        """sanitise truncates strings longer than 2048 characters."""
        long_string = "x" * 3000
        result = sanitise(long_string)
        assert isinstance(result, str)
        assert len(result) < len(long_string)
        assert "[3000 chars]" in result

    def test_sanitise_preserves_short_strings(self) -> None:
        """sanitise preserves strings shorter than 2048 characters."""
        short_string = "short string"
        result = sanitise(short_string)
        assert result == short_string

    def test_sanitise_elides_signed_urls(self) -> None:
        """sanitise elides signed URLs."""
        signed_url = "https://example.com/file?X-Amz-Signature=xyz123"
        result = sanitise(signed_url)
        assert result == REDACTED

    def test_sanitise_elides_signature_param(self) -> None:
        """sanitise elides URLs with Signature parameter."""
        url = "https://example.com/file?Signature=abc"
        result = sanitise(url)
        assert result == REDACTED

    def test_sanitise_elides_token_param(self) -> None:
        """sanitise elides URLs with token parameter."""
        url = "https://example.com?token=secret"
        result = sanitise(url)
        assert result == REDACTED

    def test_sanitise_preserves_normal_urls(self) -> None:
        """sanitise preserves normal URLs without signature."""
        normal_url = "https://example.com/file"
        result = sanitise(normal_url)
        assert result == normal_url

    def test_sanitise_primitives(self) -> None:
        """sanitise preserves primitives."""
        assert sanitise(42) == 42
        assert sanitise(3.14) == 3.14
        assert sanitise(True) is True
        assert sanitise(None) is None

    def test_sanitise_bytes_summarized(self) -> None:
        """sanitise replaces bytes with a summary."""
        result = sanitise(b"binary data")
        assert result == "<bytes 11 bytes>"

    def test_sanitise_bytearray_summarized(self) -> None:
        """sanitise replaces bytearray with a summary."""
        result = sanitise(bytearray(b"test"))
        assert result == "<bytearray 4 bytes>"

    def test_sanitise_long_list_truncated(self) -> None:
        """sanitise truncates lists longer than 64 items."""
        long_list = list(range(100))
        result = sanitise(long_list)
        assert isinstance(result, list)
        assert len(result) == 65  # 64 items + marker
        assert result[-1] == "... [100 items]"

    def test_sanitise_short_list_preserved(self) -> None:
        """sanitise preserves lists shorter than 64 items."""
        short_list = [1, 2, 3]
        result = sanitise(short_list)
        assert result == [1, 2, 3]

    def test_sanitise_tuple_converted_to_list(self) -> None:
        """sanitise converts tuples to lists."""
        result = sanitise((1, 2, 3))
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_sanitise_long_tuple_truncated(self) -> None:
        """sanitise truncates long tuples."""
        long_tuple = tuple(range(100))
        result = sanitise(long_tuple)
        assert isinstance(result, list)
        assert len(result) == 65

    def test_sanitise_set_converted_to_list(self) -> None:
        """sanitise converts sets to lists."""
        result = sanitise({1, 2, 3})
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_sanitise_dict_recursively_sanitized(self) -> None:
        """sanitise recursively sanitizes dict values."""
        value = {"api_key": "secret", "normal": "data"}
        result = sanitise(value)
        assert result["api_key"] == REDACTED
        assert result["normal"] == "data"

    def test_sanitise_object_with_shape_attribute(self) -> None:
        """sanitise summarizes objects with a shape attribute."""

        class FakeArray:
            shape = (10, 20, 3)

        result = sanitise(FakeArray())
        assert "shape=(10, 20, 3)" in result
        assert "FakeArray" in result

    def test_sanitise_object_with_len(self) -> None:
        """sanitise summarizes objects with __len__."""

        class CustomSequence:
            def __len__(self) -> int:
                return 42

        result = sanitise(CustomSequence())
        assert "len=42" in result

    def test_sanitise_unknown_object(self) -> None:
        """sanitise summarizes unknown objects without len."""

        class NoLen:
            pass

        result = sanitise(NoLen())
        assert "NoLen" in result


class TestLogContext:
    """Tests for the log_context context manager."""

    def test_log_context_rejects_unknown_fields(self) -> None:
        """log_context rejects unknown field names."""
        with pytest.raises(ValueError, match="unknown log context field"):
            with log_context(unknown_field="value"):
                pass

    def test_log_context_accepts_known_fields(self) -> None:
        """log_context accepts known context fields."""
        # Should not raise
        with log_context(run_id="r1", stage="s1", attempt=1):
            pass

    def test_log_context_nested_merge(self) -> None:
        """Nested log_context blocks merge rather than overwrite."""
        from selene_core.pipeline.logging import _current_context

        with log_context(run_id="r1"):
            with log_context(stage="s1"):
                ctx = _current_context()
                assert ctx.get("run_id") == "r1"
                assert ctx.get("stage") == "s1"

    def test_log_context_reverts_after_block(self) -> None:
        """log_context reverts after exiting the block."""
        from selene_core.pipeline.logging import _current_context

        before = _current_context().copy()
        with log_context(run_id="r1"):
            inside = _current_context()
            assert inside.get("run_id") == "r1"
        after = _current_context()
        assert after == before

    def test_log_context_none_values_ignored(self) -> None:
        """log_context ignores None values."""
        # Should not raise even though run_id is None
        with log_context(run_id=None):
            pass


class TestJsonLogFormatter:
    """Tests for JsonLogFormatter."""

    def test_json_log_formatter_produces_valid_json(self) -> None:
        """JsonLogFormatter produces valid JSON output."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_json_log_formatter_includes_timestamp(self) -> None:
        """JsonLogFormatter includes timestamp_utc field."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp_utc" in parsed

    def test_json_log_formatter_includes_level(self) -> None:
        """JsonLogFormatter includes level field."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "WARNING"

    def test_json_log_formatter_sanitizes_message(self) -> None:
        """JsonLogFormatter sanitizes the message field."""
        formatter = JsonLogFormatter()
        # Test with a long message that would be truncated
        long_msg = "x" * 3000
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=long_msg,
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        # The message should be truncated
        assert len(parsed["message"]) < len(long_msg)

    def test_json_log_formatter_includes_context_fields(self) -> None:
        """JsonLogFormatter includes context fields in output."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.run_id = "r1"
        record.stage = "s1"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["run_id"] == "r1"
        assert parsed["stage"] == "s1"

    def test_json_log_formatter_includes_payload(self) -> None:
        """JsonLogFormatter includes payload field for extra data."""
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.payload = {"key": "value"}
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "payload" in parsed

    def test_json_log_formatter_context_filter(self) -> None:
        """_ContextFilter adds context fields to records."""
        with log_context(run_id="r1", stage="s1"):
            filter = _ContextFilter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="test",
                args=(),
                exc_info=None,
            )
            filter.filter(record)
            assert record.run_id == "r1"  # type: ignore
            assert record.stage == "s1"  # type: ignore


class TestGetLogger:
    """Tests for get_logger and configure_logging."""

    @pytest.fixture(autouse=True)
    def _restore_root_logger(self) -> Generator[None, None, None]:
        """Restore root logger state after each test to prevent cross-test pollution."""
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_level = root.level
        yield
        root.handlers[:] = original_handlers
        root.setLevel(original_level)

    def test_get_logger_returns_adapter(self) -> None:
        """get_logger returns a logger adapter."""
        logger = get_logger("test.logger")
        assert logger is not None

    def test_configure_logging_installs_handler(self) -> None:
        """configure_logging installs a handler on root logger."""
        stream = io.StringIO()
        configure_logging(stream=stream)
        root = logging.getLogger()
        assert len(root.handlers) > 0

    def test_configure_logging_removes_existing_handlers(self) -> None:
        """configure_logging removes existing handlers before adding."""
        stream1 = io.StringIO()
        configure_logging(stream=stream1)
        stream2 = io.StringIO()
        configure_logging(stream=stream2)
        root = logging.getLogger()
        # Should have exactly one handler after configure_logging
        assert len(root.handlers) == 1

    def test_configure_logging_idempotent(self) -> None:
        """Calling configure_logging twice doesn't grow handler count."""
        stream1 = io.StringIO()
        configure_logging(stream=stream1)
        stream2 = io.StringIO()
        configure_logging(stream=stream2)
        root = logging.getLogger()
        # Should have exactly one handler
        assert len(root.handlers) == 1

    def test_logger_with_extra_fields(self) -> None:
        """Logging with extra fields puts them in payload."""
        stream = io.StringIO()
        configure_logging(stream=stream)
        logger = get_logger("test")
        logger.info("test message", extra={"custom_field": "custom_value"})
        output = stream.getvalue()
        assert output, "Logger should produce output"
        parsed = json.loads(output.strip())
        assert "payload" in parsed, "Non-context extra fields should be in payload"
        assert parsed["payload"]["custom_field"] == "custom_value"

    def test_logger_with_context(self) -> None:
        """Logger respects log_context when configured."""
        stream = io.StringIO()
        configure_logging(stream=stream)
        with log_context(run_id="test_run"):
            logger = get_logger("test")
            logger.info("contextual message")
        output = stream.getvalue()
        assert output, "Logger should produce output"
        parsed = json.loads(output.strip())
        assert parsed.get("run_id") == "test_run", "Context field should be top-level"
