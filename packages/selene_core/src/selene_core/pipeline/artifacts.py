"""Temporary write, verify, atomic publish, and orphan cleanup (WP-01 task 10).

The rule this module exists to enforce is that **a stale partial output is never
discoverable as a successful artefact**. Process interruption, a full disk, or a
cancellation must leave the run with either the previous state or the new one,
never a half-written file that looks finished.

The sequence for every artefact is: write into scratch, flush and fsync,
checksum, validate, then atomically move into place and fsync the directory. A
failure anywhere before the move leaves the published tree untouched.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.hashing import digest_file
from selene_core.pipeline.results import ArtifactRef, PublicationState

__all__ = [
    "ArtifactStore",
    "ArtifactVerificationError",
    "atomic_write",
]


class ArtifactVerificationError(Exception):
    """An artefact's bytes do not match what the manifest records."""

    def __init__(self, message: str, code: FailureCode) -> None:
        super().__init__(message)
        self.code = code


@contextmanager
def atomic_write(target: Path) -> Iterator[Path]:
    """Yield a temporary path whose contents replace ``target`` on clean exit.

    The temporary file is created in ``target``'s own directory so that the
    final move stays within one filesystem, where ``os.replace`` is atomic. If
    the body raises, the temporary file is removed and ``target`` is untouched.

    Args:
        target: The final path to publish to.

    Yields:
        A path to write to. Do not rename or delete it yourself.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".partial"
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        yield temporary
        _fsync_file(temporary)
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ArtifactStore:
    """The on-disk layout of one run, and the only way to publish into it.

    ::

        <root>/
          artifacts/          published, checksummed, immutable
          scratch/<stage>/<attempt>/   in-progress, never discoverable
          run.json            the run manifest

    Nothing outside this class writes into ``artifacts/``.
    """

    ARTIFACTS_DIRECTORY = "artifacts"
    SCRATCH_DIRECTORY = "scratch"
    MANIFEST_NAME = "run.json"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def artifacts_root(self) -> Path:
        """Directory holding published artefacts."""
        return self.root / self.ARTIFACTS_DIRECTORY

    @property
    def scratch_root(self) -> Path:
        """Directory holding in-progress stage output."""
        return self.root / self.SCRATCH_DIRECTORY

    @property
    def manifest_path(self) -> Path:
        """Path of the run manifest."""
        return self.root / self.MANIFEST_NAME

    def initialise(self) -> None:
        """Create the run directory structure."""
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.scratch_root.mkdir(parents=True, exist_ok=True)

    def scratch_for(self, stage_name: str, attempt: int) -> Path:
        """Return a fresh scratch directory for one stage attempt.

        Any directory left over from a previous attempt is removed first: its
        contents were never published, so they are orphaned by definition and
        reusing them would blur which attempt produced what.
        """
        directory = self.scratch_root / stage_name / str(attempt)
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        return directory

    def resolve(self, artifact: ArtifactRef) -> Path:
        """Absolute path of a published artefact."""
        return self.artifacts_root / artifact.relative_path

    def publish(
        self,
        source: Path,
        *,
        relative_path: str,
        kind: str,
        media_type: str,
        schema_id: str | None = None,
        crs_wkt: str | None = None,
        shape: tuple[int, ...] | None = None,
        nodata: float | None = None,
        units: str | None = None,
        validate: Callable[[Path], None] | None = None,
    ) -> ArtifactRef:
        """Validate a scratch file and move it into the published tree.

        Args:
            source: The scratch file to publish.
            relative_path: Destination path relative to ``artifacts/``.
            kind: The artefact's role within its stage.
            media_type: IANA media type.
            schema_id: Schema the artefact conforms to, if any.
            crs_wkt: Full CRS for a georeferenced artefact.
            shape: Raster shape, for a raster.
            nodata: Nodata value, in the artefact's own pixel units.
            units: Physical units of the pixel values.
            validate: Optional check run *before* publication. Raising from it
                leaves the published tree untouched. Kept as a callable so that
                this module needs no knowledge of where schemas live.

        Returns:
            A reference in the ``PUBLISHED`` state.

        Raises:
            ArtifactVerificationError: If the source is missing, or if something
                is already published at ``relative_path``. A published artefact
                is immutable: overwriting one would silently invalidate every
                manifest record and every claim that cites it. A re-run
                publishes to a new path and the old artefact remains as history.
            ValueError: If ``relative_path`` escapes the artefacts root.
        """
        if not source.is_file():
            raise ArtifactVerificationError(
                f"cannot publish {source}: it does not exist", FailureCode.PRODUCT_WRITE_FAILED
            )
        destination = self._checked_destination(relative_path)
        if destination.exists():
            raise ArtifactVerificationError(
                f"refusing to overwrite the published artefact {relative_path!r}; published "
                "artefacts are immutable so that manifest records stay verifiable",
                FailureCode.PRODUCT_WRITE_FAILED,
            )

        if validate is not None:
            validate(source)

        digest = digest_file(source)
        size_bytes = source.stat().st_size

        destination.parent.mkdir(parents=True, exist_ok=True)
        _fsync_file(source)
        os.replace(source, destination)
        _fsync_directory(destination.parent)

        published = ArtifactRef(
            kind=kind,
            relative_path=relative_path,
            media_type=media_type,
            sha256=digest,
            size_bytes=size_bytes,
            publication_state=PublicationState.PUBLISHED,
            schema_id=schema_id,
            crs_wkt=crs_wkt,
            shape=shape,
            nodata=nodata,
            units=units,
        )
        # Re-read what actually landed. Publication is the moment the artefact
        # becomes citable evidence, so the digest recorded against it is the
        # digest of the published bytes, not of the bytes we intended to write.
        self.verify(published)
        return published

    def _checked_destination(self, relative_path: str) -> Path:
        artifacts_root = self.artifacts_root.resolve()
        destination = (artifacts_root / relative_path).resolve()
        if not destination.is_relative_to(artifacts_root):
            raise ValueError(
                f"relative_path {relative_path!r} escapes the artefacts root; refusing to "
                "publish outside the run"
            )
        return destination

    def verify(self, artifact: ArtifactRef) -> None:
        """Recompute an artefact's checksum and size and compare.

        Raises:
            ArtifactVerificationError: If the artefact is missing, resized, or
                its bytes have changed. This is what makes a tampered or
                truncated bundle detectable without rerunning the pipeline
                (WP-09 exit criteria).
        """
        path = self.resolve(artifact)
        if not path.is_file():
            raise ArtifactVerificationError(
                f"artefact {artifact.relative_path!r} is missing from the run",
                FailureCode.PRODUCT_CHECKSUM_MISMATCH,
            )
        actual_size = path.stat().st_size
        if actual_size != artifact.size_bytes:
            raise ArtifactVerificationError(
                f"artefact {artifact.relative_path!r} is {actual_size} bytes, manifest records "
                f"{artifact.size_bytes}",
                FailureCode.PRODUCT_CHECKSUM_MISMATCH,
            )
        actual_digest = digest_file(path)
        if actual_digest != artifact.sha256:
            raise ArtifactVerificationError(
                f"artefact {artifact.relative_path!r} has digest {actual_digest}, manifest "
                f"records {artifact.sha256}",
                FailureCode.PRODUCT_CHECKSUM_MISMATCH,
            )

    def abandon(self, stage_name: str, attempt: int) -> None:
        """Discard one stage attempt's scratch directory.

        Called on cancellation and on failure. Scratch contents are orphaned,
        never published, and never reused.
        """
        directory = self.scratch_root / stage_name / str(attempt)
        if directory.exists():
            shutil.rmtree(directory)

    def cleanup_scratch(self) -> int:
        """Remove every scratch directory. Returns how many were removed."""
        if not self.scratch_root.exists():
            return 0
        removed = 0
        for stage_directory in sorted(self.scratch_root.iterdir()):
            if stage_directory.is_dir():
                shutil.rmtree(stage_directory)
                removed += 1
        return removed
