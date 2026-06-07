"""Storage-neutral analysis job helpers and worker messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shotsight2.domain.persistence import AnalysisStage, JobStatus

ANALYSIS_STAGE_ORDER: tuple[AnalysisStage, ...] = (
    AnalysisStage.VALIDATING,
    AnalysisStage.PREPROCESSING,
    AnalysisStage.SEGMENTING_CAMERA,
    AnalysisStage.AUTO_CALIBRATING,
    AnalysisStage.TRACKING,
    AnalysisStage.DETECTING_SHOTS,
    AnalysisStage.MAPPING_COURT,
    AnalysisStage.RENDERING_ARTIFACTS,
    AnalysisStage.COMPUTING_STATISTICS,
    AnalysisStage.FINALIZING,
)

ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset((JobStatus.QUEUED, JobStatus.RUNNING))
TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset((JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED))

ALLOWED_JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset((JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED)),
    JobStatus.RUNNING: frozenset((JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def validate_job_transition(current: JobStatus, target: JobStatus) -> None:
    """Reject state changes outside the approved lifecycle graph."""
    if current is target:
        return
    if target not in ALLOWED_JOB_TRANSITIONS[current]:
        raise ValueError(f"Cannot transition analysis job from {current.value} to {target.value}")


def validate_stage_transition(current: AnalysisStage, target: AnalysisStage) -> None:
    """Ensure pipeline stages never move backward."""
    if ANALYSIS_STAGE_ORDER.index(target) < ANALYSIS_STAGE_ORDER.index(current):
        raise ValueError(f"Cannot transition analysis stage from {current.value} to {target.value}")


@dataclass(frozen=True, slots=True)
class QueueMessage:
    """Identifier-only payload for one durable analysis job."""

    job_id: str
    video_id: str
    run_id: str

    def __post_init__(self) -> None:
        """Reject empty identifiers at the process boundary."""
        if not self.job_id or not self.video_id or not self.run_id:
            raise ValueError("Queue message identifiers must not be empty")


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A queue message currently owned by one worker."""

    message: QueueMessage
    worker_id: str
    claimed_at: datetime
