"""Domain types for binary artifacts managed by ShotSight."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

ArtifactId = NewType("ArtifactId", str)


class ArtifactKind(StrEnum):
    """Kinds of binary data that may be stored locally."""

    ORIGINAL = "original"
    PROXY = "proxy"
    CALIBRATION = "calibration"
    TRACK = "track"
    REPLAY = "replay"
    RENDER = "render"
    REPORT = "report"
    MODEL = "model"
    TEMPORARY = "temporary"


class ArtifactRoot(StrEnum):
    """Logical storage roots; callers never receive their physical locations."""

    UPLOAD = "upload"
    RUN = "run"
    TEMP = "temp"
    MODEL = "model"


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """Safe metadata returned to callers without a physical filesystem path."""

    artifact_id: ArtifactId
    kind: ArtifactKind
    logical_path: str
    size_bytes: int
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """All permanent artifacts owned by one video."""

    video_id: str
    artifacts: tuple[ArtifactMetadata, ...]
    total_bytes: int


@dataclass(frozen=True, slots=True)
class RootUsage:
    """Disk usage for one logical storage root."""

    root: ArtifactRoot
    file_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class StorageUsage:
    """Aggregate disk usage for all artifact roots."""

    roots: tuple[RootUsage, ...]
    total_files: int
    total_bytes: int
