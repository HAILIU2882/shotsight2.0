"""Deletion-specific domain models for videos and owned artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shotsight2.domain.artifacts import ArtifactInventory
from shotsight2.domain.persistence import AnalysisJob, Artifact, Video


class DeletionStatus(StrEnum):
    """User-visible outcome of a deletion request."""

    DELETED = "DELETED"
    ALREADY_DELETED = "ALREADY_DELETED"
    CLEANUP_INCOMPLETE = "CLEANUP_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class DeletionRecordCounts:
    """Counts of video-owned database records affected by deletion."""

    videos: int = 0
    analysis_runs: int = 0
    analysis_jobs: int = 0
    camera_segments: int = 0
    calibrations: int = 0
    player_tracks: int = 0
    ball_tracks: int = 0
    shot_attempts: int = 0
    shot_locations: int = 0
    review_corrections: int = 0
    artifact_metadata: int = 0

    @property
    def total(self) -> int:
        """Return the total number of database records represented."""
        return (
            self.videos
            + self.analysis_runs
            + self.analysis_jobs
            + self.camera_segments
            + self.calibrations
            + self.player_tracks
            + self.ball_tracks
            + self.shot_attempts
            + self.shot_locations
            + self.review_corrections
            + self.artifact_metadata
        )


@dataclass(frozen=True, slots=True)
class DeletionInventory:
    """Safe pre-deletion inventory without physical filesystem paths."""

    video_id: str
    video: Video | None
    record_counts: DeletionRecordCounts
    artifact_metadata: tuple[Artifact, ...]
    filesystem_artifacts: ArtifactInventory
    active_jobs: tuple[AnalysisJob, ...] = ()

    @property
    def total_bytes(self) -> int:
        """Return total filesystem bytes currently owned by the video."""
        return self.filesystem_artifacts.total_bytes


@dataclass(frozen=True, slots=True)
class DeletionFailure:
    """Sanitized cleanup failure details safe for audit logs and UI."""

    error_type: str
    remaining_artifacts: ArtifactInventory


@dataclass(frozen=True, slots=True)
class DeletionResult:
    """Result returned after attempting video deletion."""

    video_id: str
    status: DeletionStatus
    inventory: DeletionInventory
    failure: DeletionFailure | None = None
