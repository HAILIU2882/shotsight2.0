"""Filesystem infrastructure adapters."""

from shotsight2.adapters.filesystem.artifact_store import (
    ArtifactStoreRoots,
    FileSystemArtifactStore,
)

__all__ = ["ArtifactStoreRoots", "FileSystemArtifactStore"]
