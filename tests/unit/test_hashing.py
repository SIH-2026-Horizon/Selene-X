"""Tests for content and provenance hashing.

Covers canonical_json, digest_json, digest_file, digest_many, and is_sha256.
"""

import hashlib
from pathlib import Path

import pytest

from selene_core.pipeline.hashing import (
    EMPTY_DIGEST,
    canonical_json,
    digest_file,
    digest_json,
    digest_many,
    is_sha256,
)

pytestmark = pytest.mark.unit


class TestCanonicalJson:
    """Tests for canonical_json serialization."""

    def test_canonical_json_sorts_keys(self) -> None:
        """canonical_json produces sorted keys."""
        value = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(value)
        assert '"a":2' in result
        assert result.index('"a"') < result.index('"m"') < result.index('"z"')

    def test_canonical_json_no_whitespace(self) -> None:
        """canonical_json uses compact separators."""
        value = {"x": 1, "y": [2, 3]}
        result = canonical_json(value)
        assert " " not in result
        assert result == '{"x":1,"y":[2,3]}'

    def test_canonical_json_preserves_non_ascii(self) -> None:
        """canonical_json preserves non-ASCII characters."""
        value = {"name": "Moon", "emoji": "🌙"}
        result = canonical_json(value)
        assert "🌙" in result
        assert "\\u" not in result

    def test_canonical_json_rejects_nan(self) -> None:
        """canonical_json rejects NaN."""
        value = {"x": float("nan")}
        with pytest.raises(ValueError, match="non-finite float"):
            canonical_json(value)

    def test_canonical_json_rejects_infinity(self) -> None:
        """canonical_json rejects positive infinity."""
        value = {"x": float("inf")}
        with pytest.raises(ValueError, match="non-finite float"):
            canonical_json(value)

    def test_canonical_json_rejects_negative_infinity(self) -> None:
        """canonical_json rejects negative infinity."""
        value = {"x": float("-inf")}
        with pytest.raises(ValueError, match="non-finite float"):
            canonical_json(value)

    def test_canonical_json_nested_structures(self) -> None:
        """canonical_json handles nested structures."""
        value = {"outer": {"inner": {"deep": [1, 2, 3]}, "list": [{"a": 1}]}}
        result = canonical_json(value)
        parsed = canonical_json(value)  # Should be deterministic
        assert parsed == result

    def test_canonical_json_dict_key_ordering_deterministic(self) -> None:
        """canonical_json produces identical output regardless of insertion order."""
        dict1 = {"a": 1, "b": 2, "c": 3}
        dict2 = {"c": 3, "b": 2, "a": 1}
        assert canonical_json(dict1) == canonical_json(dict2)

    def test_canonical_json_accepts_valid_floats(self) -> None:
        """canonical_json accepts finite floats."""
        value = {"pi": 3.14159, "e": 2.71828}
        result = canonical_json(value)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_canonical_json_null_values(self) -> None:
        """canonical_json preserves null values."""
        value = {"x": None, "y": 1}
        result = canonical_json(value)
        assert "null" in result


class TestDigestJson:
    """Tests for digest_json."""

    def test_digest_json_same_input_same_output(self) -> None:
        """digest_json produces identical digests for identical inputs."""
        value = {"x": 1, "y": 2}
        digest1 = digest_json(value)
        digest2 = digest_json(value)
        assert digest1 == digest2

    def test_digest_json_key_order_independent(self) -> None:
        """digest_json produces same digest regardless of key order."""
        dict1 = {"a": 1, "b": 2, "c": 3}
        dict2 = {"c": 3, "a": 1, "b": 2}
        assert digest_json(dict1) == digest_json(dict2)

    def test_digest_json_is_sha256(self) -> None:
        """digest_json produces a valid SHA-256 hex digest."""
        value = {"test": "data"}
        digest = digest_json(value)
        assert is_sha256(digest)

    def test_digest_json_non_serializable_object_raises(self) -> None:
        """digest_json raises TypeError for non-JSON-serializable objects."""
        value = {"x": object()}
        with pytest.raises(TypeError):
            digest_json(value)

    def test_digest_json_different_values_different_digests(self) -> None:
        """digest_json produces different digests for different values."""
        digest1 = digest_json({"x": 1})
        digest2 = digest_json({"x": 2})
        assert digest1 != digest2

    def test_digest_json_list_values(self) -> None:
        """digest_json handles list values."""
        value = [1, 2, 3]
        digest = digest_json(value)
        assert is_sha256(digest)


class TestDigestFile:
    """Tests for digest_file."""

    def test_digest_file_empty_file(self, tmp_path: Path) -> None:
        """digest_file matches EMPTY_DIGEST for an empty file."""
        empty_file = tmp_path / "empty.bin"
        empty_file.write_bytes(b"")
        assert digest_file(empty_file) == EMPTY_DIGEST

    def test_digest_file_matches_hashlib(self, tmp_path: Path) -> None:
        """digest_file matches hashlib.sha256 on a real file."""
        test_file = tmp_path / "test.bin"
        content = b"test content"
        test_file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert digest_file(test_file) == expected

    def test_digest_file_large_file_streaming(self, tmp_path: Path) -> None:
        """digest_file works on files larger than _CHUNK_BYTES (1 MiB)."""
        large_file = tmp_path / "large.bin"
        # Write 1 MiB + 1 byte to exceed chunk size
        content = b"\x00" * (1024 * 1024 + 1)
        large_file.write_bytes(content)
        digest = digest_file(large_file)
        assert is_sha256(digest)
        expected = hashlib.sha256(content).hexdigest()
        assert digest == expected

    def test_digest_file_small_file(self, tmp_path: Path) -> None:
        """digest_file correctly hashes small files."""
        test_file = tmp_path / "small.bin"
        # Write 3 bytes in total (less than chunk size)
        test_file.write_bytes(b"abc")
        expected = hashlib.sha256(b"abc").hexdigest()
        assert digest_file(test_file) == expected

    def test_digest_file_deterministic(self, tmp_path: Path) -> None:
        """digest_file produces same digest for same content."""
        test_file = tmp_path / "test.bin"
        content = b"deterministic content"
        test_file.write_bytes(content)
        digest1 = digest_file(test_file)
        digest2 = digest_file(test_file)
        assert digest1 == digest2


class TestDigestMany:
    """Tests for digest_many."""

    def test_digest_many_order_independent(self) -> None:
        """digest_many produces same digest regardless of input order."""
        digest_a = "a" * 64
        digest_b = "b" * 64
        list1 = [digest_a, digest_b]
        list2 = [digest_b, digest_a]
        # Mock valid SHA-256s for testing
        digest1 = digest_many(list1)
        digest2 = digest_many(list2)
        assert digest1 == digest2

    def test_digest_many_valid_digests_required(self) -> None:
        """digest_many requires all inputs to be valid SHA-256 digests."""
        valid_digest = "a" * 64
        invalid_digest = "not_a_digest"
        with pytest.raises(ValueError, match="not a SHA-256 hex digest"):
            digest_many([valid_digest, invalid_digest])

    def test_digest_many_uppercase_rejected(self) -> None:
        """digest_many rejects uppercase hex digits."""
        digest_lower = "a" * 64
        digest_upper = "A" * 64
        with pytest.raises(ValueError, match="not a SHA-256 hex digest"):
            digest_many([digest_lower, digest_upper])

    def test_digest_many_single_digest(self) -> None:
        """digest_many works with a single digest."""
        digest = "a" * 64
        result = digest_many([digest])
        assert is_sha256(result)

    def test_digest_many_produces_sha256(self) -> None:
        """digest_many produces a valid SHA-256 digest."""
        digest_a = "0" * 64
        digest_b = "1" * 64
        result = digest_many([digest_a, digest_b])
        assert is_sha256(result)


class TestIsSha256:
    """Tests for is_sha256 validation."""

    def test_is_sha256_valid_digest(self) -> None:
        """is_sha256 returns True for a valid 64-char lowercase hex digest."""
        valid_digest = "0" * 64
        assert is_sha256(valid_digest)

    def test_is_sha256_valid_mixed_hex(self) -> None:
        """is_sha256 accepts lowercase hex characters."""
        valid_digest = "abcdef0123456789" * 4
        assert is_sha256(valid_digest)

    def test_is_sha256_uppercase_rejected(self) -> None:
        """is_sha256 returns False for uppercase hex digits."""
        digest = "A" * 64
        assert not is_sha256(digest)

    def test_is_sha256_mixed_case_rejected(self) -> None:
        """is_sha256 returns False for mixed case."""
        digest = "abcdef" * 10 + "ABCDEF"
        assert not is_sha256(digest)

    def test_is_sha256_too_short(self) -> None:
        """is_sha256 returns False for digests shorter than 64 chars."""
        digest = "a" * 63
        assert not is_sha256(digest)

    def test_is_sha256_too_long(self) -> None:
        """is_sha256 returns False for digests longer than 64 chars."""
        digest = "a" * 65
        assert not is_sha256(digest)

    def test_is_sha256_non_hex_character(self) -> None:
        """is_sha256 returns False for non-hex characters."""
        digest = "z" * 64
        assert not is_sha256(digest)

    def test_is_sha256_empty_string(self) -> None:
        """is_sha256 returns False for empty string."""
        assert not is_sha256("")

    def test_is_sha256_all_zeros(self) -> None:
        """is_sha256 returns True for all-zero digest."""
        digest = "0" * 64
        assert is_sha256(digest)
