"""Port for safe local binary artifact storage."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol

from shotsight2.domain.artifacts import (
    ArtifactId,
    ArtifactInventory,
    ArtifactMetadata,
    StorageUsage,
)


class ArtifactStoreError(Exception):
    """Base class for artifact-store failures."""


class InvalidArtifactIdError(ArtifactStoreError):
    """Raised when an artifact identifier is malformed or unsafe."""


class UnknownArtifactError(ArtifactStoreError):
    """Raised when a requested artifact does not exist."""


class DuplicateArtifactError(ArtifactStoreError):
    """Raised when promotion would replace a completed artifact."""


class UnsafeFilesystemError(ArtifactStoreError):
    """Raised when a symlink or other unsafe filesystem object is encountered."""


class ArtifactStore(Protocol):
    """Manage binary artifacts exclusively through logical identifiers."""

    def original_id(self, video_id: str, extension: str) -> ArtifactId:
        """Return the canonical original-video identifier."""

    def proxy_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return an analysis proxy identifier."""

    def track_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a track-data identifier."""

    def replay_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a replay-video identifier."""

    def render_id(self, video_id: str, run_id: str, filename: str) -> ArtifactId:
        """Return a rendered-output identifier."""

    def model_id(self, backend: str, filename: str) -> ArtifactId:
        """Return a shared model identifier."""

    def create_temporary_file(self, video_id: str, run_id: str, *, suffix: str = "") -> ArtifactId:
        """Create an empty temporary file scoped to a video and run."""

    def create_temporary_directory(self, video_id: str, run_id: str) -> ArtifactId:
        """Create a temporary directory scoped to a video and run."""

    def write_atomic(self, artifact_id: ArtifactId, chunks: Iterable[bytes]) -> ArtifactMetadata:
        """Write a completed artifact without exposing a partial destination."""

    def promote(self, temporary_id: ArtifactId, destination_id: ArtifactId) -> ArtifactMetadata:
        """Atomically promote an existing temporary file."""

    def open_read(self, artifact_id: ArtifactId) -> AbstractContextManager[BinaryIO]:
        """Open a known artifact for streaming reads."""

    def metadata(self, artifact_id: ArtifactId) -> ArtifactMetadata:
        """Return safe metadata for an existing artifact."""

    def inventory_for_video(self, video_id: str) -> ArtifactInventory:
        """Return all permanent artifacts owned by a video."""

    def storage_usage(self) -> StorageUsage:
        """Calculate artifact disk usage."""

    def delete_video_tree(self, video_id: str) -> ArtifactInventory:
        """Delete all video-owned artifacts and return the deleted inventory."""
