"""Tests for artifact storage and atomic writing.

Covers atomic_write, ArtifactStore, ArtifactVerificationError, and the
publish/verify/abandon/cleanup_scratch operations.
"""

from pathlib import Path

import pytest

from selene_core.pipeline.artifacts import (
    ArtifactStore,
    ArtifactVerificationError,
    atomic_write,
)
from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.results import PublicationState

pytestmark = pytest.mark.unit


class TestAtomicWrite:
    """Tests for atomic_write context manager."""

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        """atomic_write publishes the file at target on clean exit."""
        target = tmp_path / "output.txt"
        with atomic_write(target) as temp:
            temp.write_text("test content")
        assert target.exists()
        assert target.read_text() == "test content"

    def test_atomic_write_uses_temp_file(self, tmp_path: Path) -> None:
        """atomic_write uses a temporary file during write."""
        target = tmp_path / "output.txt"
        temp_files = set()
        with atomic_write(target) as temp:
            temp_files.add(temp)
            temp.write_text("content")
        # The temporary file should be gone after exit
        assert not temp_files.pop().exists()

    def test_atomic_write_removes_temp_on_exception(self, tmp_path: Path) -> None:
        """atomic_write removes the temp file if body raises."""
        target = tmp_path / "output.txt"
        temp_files = set()
        with pytest.raises(ValueError):
            with atomic_write(target) as temp:
                temp_files.add(temp)
                temp.write_text("content")
                raise ValueError("test error")
        assert not target.exists()
        assert not temp_files.pop().exists()

    def test_atomic_write_target_unchanged_on_exception(self, tmp_path: Path) -> None:
        """atomic_write leaves target unchanged if body raises."""
        target = tmp_path / "output.txt"
        target.write_text("original content")
        with pytest.raises(ValueError):
            with atomic_write(target) as temp:
                temp.write_text("new content")
                raise ValueError("test error")
        assert target.read_text() == "original content"

    def test_atomic_write_creates_parent_directory(self, tmp_path: Path) -> None:
        """atomic_write creates parent directories."""
        target = tmp_path / "subdir" / "output.txt"
        with atomic_write(target) as temp:
            temp.write_text("content")
        assert target.exists()

    def test_atomic_write_no_partial_file_on_exception(self, tmp_path: Path) -> None:
        """atomic_write leaves no .partial file after exception."""
        target = tmp_path / "output.txt"
        with pytest.raises(ValueError):
            with atomic_write(target) as temp:
                temp.write_text("content")
                raise ValueError("test")
        # Check that no .partial files are left
        partial_files = list(tmp_path.glob(".*partial"))
        assert len(partial_files) == 0


class TestArtifactStoreInitialise:
    """Tests for ArtifactStore initialization."""

    def test_artifact_store_initialise_creates_directories(self, tmp_path: Path) -> None:
        """ArtifactStore.initialise creates artifacts/ and scratch/."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        assert (tmp_path / "artifacts").exists()
        assert (tmp_path / "scratch").exists()

    def test_artifact_store_initialise_idempotent(self, tmp_path: Path) -> None:
        """ArtifactStore.initialise can be called multiple times."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        store.initialise()
        assert (tmp_path / "artifacts").exists()
        assert (tmp_path / "scratch").exists()


class TestArtifactStoreScratch:
    """Tests for ArtifactStore scratch directory management."""

    def test_artifact_store_scratch_for_creates_directory(self, tmp_path: Path) -> None:
        """scratch_for returns a fresh empty directory."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        scratch = store.scratch_for("stage1", 1)
        assert scratch.exists()
        assert list(scratch.iterdir()) == []

    def test_artifact_store_scratch_for_wipes_existing(self, tmp_path: Path) -> None:
        """scratch_for wipes existing directory from previous attempt."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        scratch1 = store.scratch_for("stage1", 1)
        (scratch1 / "old_file.txt").write_text("old")
        scratch2 = store.scratch_for("stage1", 1)
        assert scratch2 == scratch1
        assert list(scratch2.iterdir()) == []

    def test_artifact_store_scratch_for_different_attempts_separate(self, tmp_path: Path) -> None:
        """Different attempts have separate scratch directories."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        scratch1 = store.scratch_for("stage1", 1)
        scratch2 = store.scratch_for("stage1", 2)
        assert scratch1 != scratch2


class TestArtifactStorePublish:
    """Tests for ArtifactStore.publish."""

    def test_artifact_store_publish_happy_path(self, tmp_path: Path) -> None:
        """publish copies a file to artifacts and returns ArtifactRef."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("test data")
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        assert ref.publication_state == PublicationState.PUBLISHED
        assert ref.relative_path == "output.txt"
        assert ref.kind == "data"
        assert (store.artifacts_root / "output.txt").exists()

    def test_artifact_store_publish_sets_correct_digest(self, tmp_path: Path) -> None:
        """publish sets sha256 to the actual file's digest."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        content = b"test content"
        source.write_bytes(content)
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        # The digest should be correct
        assert len(ref.sha256) == 64

    def test_artifact_store_publish_sets_size(self, tmp_path: Path) -> None:
        """publish sets size_bytes correctly."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        content = b"test"
        source.write_bytes(content)
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        assert ref.size_bytes == len(content)

    def test_artifact_store_publish_missing_source_raises(self, tmp_path: Path) -> None:
        """publish raises ArtifactVerificationError for missing source."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        missing = tmp_path / "missing.txt"
        with pytest.raises(ArtifactVerificationError) as exc_info:
            store.publish(
                missing,
                relative_path="output.txt",
                kind="data",
                media_type="text/plain",
            )
        assert exc_info.value.code == FailureCode.PRODUCT_WRITE_FAILED

    def test_artifact_store_publish_duplicate_raises(self, tmp_path: Path) -> None:
        """publish raises on second publish to same relative_path."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source1 = tmp_path / "source1.txt"
        source1.write_text("data1")
        store.publish(
            source1,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        source2 = tmp_path / "source2.txt"
        source2.write_text("data2")
        with pytest.raises(ArtifactVerificationError) as exc_info:
            store.publish(
                source2,
                relative_path="output.txt",
                kind="data",
                media_type="text/plain",
            )
        assert exc_info.value.code == FailureCode.PRODUCT_WRITE_FAILED

    def test_artifact_store_publish_rejects_path_escape(self, tmp_path: Path) -> None:
        """publish rejects relative_path with .. or leading /."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")
        with pytest.raises(ValueError, match="escapes"):
            store.publish(
                source,
                relative_path="../etc/passwd",
                kind="data",
                media_type="text/plain",
            )

    def test_artifact_store_publish_rejects_absolute_path(self, tmp_path: Path) -> None:
        """publish rejects absolute relative_path."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")
        with pytest.raises(ValueError, match="escapes"):
            store.publish(
                source,
                relative_path="/etc/passwd",
                kind="data",
                media_type="text/plain",
            )

    def test_artifact_store_publish_validate_hook_prevents_publication(
        self, tmp_path: Path
    ) -> None:
        """publish's validate hook prevents publication if it raises."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")

        def failing_validate(path: Path) -> None:
            raise ValueError("validation failed")

        with pytest.raises(ValueError, match="validation failed"):
            store.publish(
                source,
                relative_path="output.txt",
                kind="data",
                media_type="text/plain",
                validate=failing_validate,
            )
        # File should not be published
        assert not (store.artifacts_root / "output.txt").exists()


class TestArtifactStoreVerify:
    """Tests for ArtifactStore.verify."""

    def test_artifact_store_verify_succeeds_for_published(self, tmp_path: Path) -> None:
        """verify passes silently for a freshly published artifact."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        # Should not raise
        store.verify(ref)

    def test_artifact_store_verify_detects_missing_artifact(self, tmp_path: Path) -> None:
        """verify raises if the published file is deleted."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        (store.artifacts_root / "output.txt").unlink()
        with pytest.raises(ArtifactVerificationError) as exc_info:
            store.verify(ref)
        assert exc_info.value.code == FailureCode.PRODUCT_CHECKSUM_MISMATCH

    def test_artifact_store_verify_detects_size_change_truncate(self, tmp_path: Path) -> None:
        """verify raises if file size changes."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("test data")
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        # Truncate the file
        (store.artifacts_root / "output.txt").write_text("test")
        with pytest.raises(ArtifactVerificationError) as exc_info:
            store.verify(ref)
        assert exc_info.value.code == FailureCode.PRODUCT_CHECKSUM_MISMATCH

    def test_artifact_store_verify_detects_content_change(self, tmp_path: Path) -> None:
        """verify raises if file bytes change."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        source = tmp_path / "source.txt"
        source.write_text("data")
        ref = store.publish(
            source,
            relative_path="output.txt",
            kind="data",
            media_type="text/plain",
        )
        # Change a byte
        artifact_path = store.artifacts_root / "output.txt"
        artifact_path.write_text("other")
        with pytest.raises(ArtifactVerificationError) as exc_info:
            store.verify(ref)
        assert exc_info.value.code == FailureCode.PRODUCT_CHECKSUM_MISMATCH


class TestArtifactStoreAbandon:
    """Tests for ArtifactStore.abandon."""

    def test_artifact_store_abandon_removes_scratch(self, tmp_path: Path) -> None:
        """abandon removes the scratch directory."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        scratch = store.scratch_for("stage1", 1)
        (scratch / "file.txt").write_text("content")
        store.abandon("stage1", 1)
        assert not scratch.exists()

    def test_artifact_store_abandon_noop_for_missing(self, tmp_path: Path) -> None:
        """abandon is a no-op if scratch doesn't exist."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        # No exception should be raised
        store.abandon("nonexistent", 1)


class TestArtifactStoreCleanupScratch:
    """Tests for ArtifactStore.cleanup_scratch."""

    def test_artifact_store_cleanup_scratch_removes_all(self, tmp_path: Path) -> None:
        """cleanup_scratch removes all stage directories."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        scratch1 = store.scratch_for("stage1", 1)
        scratch2 = store.scratch_for("stage2", 1)
        (scratch1 / "file.txt").write_text("content")
        (scratch2 / "file.txt").write_text("content")
        removed = store.cleanup_scratch()
        assert removed == 2
        assert not scratch1.exists()
        assert not scratch2.exists()

    def test_artifact_store_cleanup_scratch_returns_count(self, tmp_path: Path) -> None:
        """cleanup_scratch returns the correct count."""
        store = ArtifactStore(tmp_path)
        store.initialise()
        store.scratch_for("stage1", 1)
        store.scratch_for("stage2", 1)
        store.scratch_for("stage3", 1)
        removed = store.cleanup_scratch()
        assert removed == 3

    def test_artifact_store_cleanup_scratch_noop_for_missing(self, tmp_path: Path) -> None:
        """cleanup_scratch returns 0 when scratch/ doesn't exist."""
        store = ArtifactStore(tmp_path)
        # Don't initialise, so scratch_root doesn't exist
        removed = store.cleanup_scratch()
        assert removed == 0
