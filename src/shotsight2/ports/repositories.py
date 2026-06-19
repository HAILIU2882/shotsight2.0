"""Repository protocols that keep SQLite details outside application code."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from shotsight2.domain import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Artifact,
    AssociationEvidenceReference,
    BackupMetadata,
    BallTrack,
    Calibration,
    CameraSegment,
    EffectiveShotAttempt,
    JobStatus,
    PlayerTrack,
    ReviewCorrection,
    ShotAttempt,
    ShotLocation,
    Video,
)
from shotsight2.domain.deletion import DeletionRecordCounts
from shotsight2.domain.persistence import JsonObject


class VideoRepository(Protocol):
    """Persist and query uploaded video metadata."""

    def create(self, video: Video) -> None: ...
    def get(self, video_id: str) -> Video | None: ...
    def list(self) -> list[Video]: ...
    def mark_deleting(self, video_id: str) -> None: ...
    def delete(self, video_id: str) -> None: ...


class AnalysisRunRepository(Protocol):
    """Persist analysis lifecycle state and atomically publish completed results."""

    def create(self, run: AnalysisRun) -> None: ...
    def get(self, run_id: str) -> AnalysisRun | None: ...
    def list_for_video(self, video_id: str, *, published_only: bool = False) -> list[AnalysisRun]: ...
    def update_progress(self, run_id: str, progress: float, stage: AnalysisStage) -> None: ...
    def fail(self, run_id: str, error: JsonObject) -> None: ...
    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None: ...


class JobRepository(Protocol):
    """Persist durable identifiers and state for local worker jobs."""

    def create(self, job: AnalysisJob) -> None: ...
    def get(self, job_id: str) -> AnalysisJob | None: ...
    def list_for_video(self, video_id: str) -> list[AnalysisJob]: ...
    def list_active(self) -> list[AnalysisJob]: ...
    def update_state(
        self,
        job_id: str,
        status: JobStatus,
        stage: AnalysisStage,
        progress: float,
        *,
        error: JsonObject | None = None,
    ) -> None: ...


class CameraSegmentRepository(Protocol):
    """Persist stable camera ranges produced by an analysis run."""

    def replace_for_run(self, run_id: str, segments: Sequence[CameraSegment]) -> None: ...
    def get(self, segment_id: str) -> CameraSegment | None: ...
    def list_for_run(self, run_id: str) -> list[CameraSegment]: ...


class CalibrationRepository(Protocol):
    """Persist append-only calibration versions for each segment."""

    def add(self, calibration: Calibration) -> None: ...
    def list_for_segment(self, segment_id: str) -> list[Calibration]: ...
    def latest_for_segment(self, segment_id: str) -> Calibration | None: ...


class PlayerTrackRepository(Protocol):
    """Persist video-local player identities."""

    def replace_for_run(self, run_id: str, tracks: Sequence[PlayerTrack]) -> None: ...
    def list_for_run(self, run_id: str) -> list[PlayerTrack]: ...
    def list_for_video(self, video_id: str) -> list[PlayerTrack]: ...
    def rename_display_name(self, player_track_id: str, display_name: str) -> None: ...


class BallTrackRepository(Protocol):
    """Persist basketball-track metadata."""

    def replace_for_run(self, run_id: str, tracks: Sequence[BallTrack]) -> None: ...
    def list_for_run(self, run_id: str) -> list[BallTrack]: ...


class ShotAttemptRepository(Protocol):
    """Persist automatic attempts and query correction-aware projections."""

    def replace_automatic_results(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
    ) -> None: ...
    def add_manual_attempt(self, attempt: ShotAttempt, location: ShotLocation | None = None) -> None: ...
    def list_for_run(self, run_id: str) -> list[ShotAttempt]: ...
    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]: ...


class AssociationEvidenceRepository(Protocol):
    """Persist reviewable evidence references for shot attribution."""

    def replace_for_attempt(
        self,
        shot_attempt_id: str,
        references: Sequence[AssociationEvidenceReference],
    ) -> None: ...
    def list_for_attempt(self, shot_attempt_id: str) -> list[AssociationEvidenceReference]: ...
    def list_for_run(self, run_id: str) -> list[AssociationEvidenceReference]: ...


class CourtMappingAttemptRepository(Protocol):
    """Read attempts and atomically refresh court-derived fields."""

    def list_for_run(self, run_id: str) -> list[ShotAttempt]: ...
    def update_location_and_shot_type(
        self,
        attempt_id: str,
        location: ShotLocation,
        shot_type: str,
    ) -> None: ...
    def clear_location_and_shot_type(self, attempt_id: str, shot_type: str) -> None: ...


class ShotLocationRepository(Protocol):
    """Persist and retrieve automatic shot locations."""

    def get_for_attempt(self, attempt_id: str) -> ShotLocation | None: ...
    def upsert(self, location: ShotLocation) -> None: ...


class ReviewCorrectionRepository(Protocol):
    """Append, inspect, and remove user corrections without changing evidence."""

    def add(self, correction: ReviewCorrection) -> None: ...
    def list_for_attempt(self, attempt_id: str) -> list[ReviewCorrection]: ...
    def delete(self, correction_id: str) -> None: ...


class ArtifactRepository(Protocol):
    """Persist logical artifact metadata, never file content."""

    def add(self, artifact: Artifact) -> None: ...
    def list_for_run(self, run_id: str) -> list[Artifact]: ...
    def list_for_video(self, video_id: str) -> list[Artifact]: ...


class DeletionRepository(Protocol):
    """Coordinate deletion-specific inventory, lifecycle, and cleanup writes."""

    def inventory_counts(self, video_id: str) -> DeletionRecordCounts: ...
    def prepare_video_deletion(self, video_id: str) -> list[AnalysisJob]: ...
    def mark_cleanup_incomplete(self, video_id: str) -> None: ...
    def delete_owned_records(self, video_id: str) -> None: ...


class DiagnosticRepository(Protocol):
    """Report database backup metadata without copying user video content."""

    def backup_metadata(self) -> BackupMetadata: ...
