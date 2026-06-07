"""Storage-neutral domain records persisted by ShotSight repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class VideoStatus(StrEnum):
    """Lifecycle states for an uploaded source video."""

    READY = "READY"
    DELETING = "DELETING"
    CLEANUP_INCOMPLETE = "CLEANUP_INCOMPLETE"


class RunStatus(StrEnum):
    """Lifecycle states for an immutable analysis run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    """Durable analysis job states."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AnalysisStage(StrEnum):
    """Ordered user-visible stages in the analysis pipeline."""

    VALIDATING = "VALIDATING"
    PREPROCESSING = "PREPROCESSING"
    SEGMENTING_CAMERA = "SEGMENTING_CAMERA"
    AUTO_CALIBRATING = "AUTO_CALIBRATING"
    TRACKING = "TRACKING"
    DETECTING_SHOTS = "DETECTING_SHOTS"
    MAPPING_COURT = "MAPPING_COURT"
    RENDERING_ARTIFACTS = "RENDERING_ARTIFACTS"
    COMPUTING_STATISTICS = "COMPUTING_STATISTICS"
    FINALIZING = "FINALIZING"


class ShotOutcome(StrEnum):
    """Automatic or effective result of a released shot."""

    MADE = "MADE"
    MISSED = "MISSED"
    UNCERTAIN = "UNCERTAIN"


class ReviewStatus(StrEnum):
    """Review state of an attempt."""

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"


@dataclass(frozen=True, slots=True)
class Video:
    """Metadata for one locally stored source video."""

    id: str
    filename: str
    original_artifact_id: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str
    container: str
    created_at: datetime
    status: VideoStatus = VideoStatus.READY


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    """Versioned analysis of a video."""

    id: str
    video_id: str
    status: RunStatus
    backend_name: str
    backend_version: str
    configuration: JsonObject
    progress: float
    stage: AnalysisStage
    started_at: datetime
    completed_at: datetime | None = None
    error: JsonObject | None = None
    published: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    """Durable work item consumed by the local analysis worker."""

    id: str
    video_id: str
    run_id: str
    status: JobStatus
    stage: AnalysisStage
    progress: float
    created_at: datetime
    updated_at: datetime
    error: JsonObject | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CameraSegment:
    """Stable or unstable time range with independent tracking state."""

    id: str
    analysis_run_id: str
    start_seconds: float
    end_seconds: float
    stability_status: str
    confidence: float
    representative_artifact_id: str | None = None


@dataclass(frozen=True, slots=True)
class Calibration:
    """Versioned rim and court calibration for a camera segment."""

    id: str
    segment_id: str
    source: str
    rim_geometry: JsonObject
    court_points: JsonObject
    confidence: float
    indicative_only: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerTrack:
    """Video-local player identity produced by one analysis run."""

    id: str
    analysis_run_id: str
    video_id: str
    local_label: str
    display_name: str
    confidence: float
    observations_artifact_id: str | None = None


@dataclass(frozen=True, slots=True)
class BallTrack:
    """Basketball trajectory metadata whose observations live in an artifact."""

    id: str
    segment_id: str
    observations_artifact_id: str
    backend_name: str
    coverage: float
    identity_switches: int


@dataclass(frozen=True, slots=True)
class ShotLocation:
    """Automatic or manually supplied shot location."""

    id: str
    shot_attempt_id: str
    court_x_m: float | None
    court_y_m: float | None
    normalized_x: float
    normalized_y: float
    region: str
    indicative: bool


@dataclass(frozen=True, slots=True)
class ShotAttempt:
    """Immutable automatic evidence for one released shot."""

    id: str
    analysis_run_id: str
    shooter_track_id: str | None
    release_seconds: float
    automatic_outcome: ShotOutcome
    shot_type: str
    confidence: float
    review_status: ReviewStatus
    evidence: JsonObject
    manual: bool = False


@dataclass(frozen=True, slots=True)
class ReviewCorrection:
    """Append-only human correction of one attempt field."""

    id: str
    shot_attempt_id: str
    field: str
    previous_value: JsonValue
    corrected_value: JsonValue
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EffectiveShotAttempt:
    """Projection of automatic evidence plus the latest human corrections."""

    automatic: ShotAttempt
    shooter_track_id: str | None
    outcome: ShotOutcome
    shot_type: str
    review_status: ReviewStatus
    location: ShotLocation | None
    removed: bool


@dataclass(frozen=True, slots=True)
class Artifact:
    """Metadata for a generated or source file managed by the artifact store."""

    id: str
    video_id: str
    analysis_run_id: str | None
    kind: str
    logical_path: str
    version: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    """Small diagnostic snapshot that deliberately excludes video content."""

    schema_version: int
    database_path: str
    database_size_bytes: int
    video_count: int
    analysis_run_count: int
    generated_at: datetime
