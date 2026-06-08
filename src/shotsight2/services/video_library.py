"""Read-only video library dashboard projections."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from shotsight2.domain import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Artifact,
    EffectiveShotAttempt,
    JobStatus,
    PlayerTrack,
    ReviewStatus,
    RunStatus,
    ShotOutcome,
    Video,
    VideoStatus,
)
from shotsight2.domain.persistence import JsonObject, JsonValue
from shotsight2.ports.repositories import (
    AnalysisRunRepository,
    ArtifactRepository,
    JobRepository,
    PlayerTrackRepository,
    ShotAttemptRepository,
    VideoRepository,
)

DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.60
TWO_POINT_SHOT_TYPE = "TWO_POINT"
THREE_POINT_SHOT_TYPE = "THREE_POINT"
type SortKey = tuple[datetime, str]


class LibraryState(StrEnum):
    """Top-level library population state."""

    EMPTY = "EMPTY"
    POPULATED = "POPULATED"


class AnalysisProjectionState(StrEnum):
    """Dashboard-friendly analysis state for one video."""

    NEVER_ANALYZED = "NEVER_ANALYZED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class FailureSummary:
    """Safe failure details suitable for dashboards."""

    category: str
    message: str
    stage: AnalysisStage | None = None


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Analysis run lifecycle projection."""

    run_id: str
    status: RunStatus
    stage: AnalysisStage
    progress: float
    started_at: datetime
    completed_at: datetime | None
    backend_name: str
    published: bool
    failure: FailureSummary | None


@dataclass(frozen=True, slots=True)
class JobSummary:
    """Analysis job lifecycle projection."""

    job_id: str
    run_id: str
    status: JobStatus
    stage: AnalysisStage
    progress: float
    created_at: datetime
    updated_at: datetime
    failure: FailureSummary | None


@dataclass(frozen=True, slots=True)
class AnalysisStatusSummary:
    """Latest and published analysis state for one video."""

    state: AnalysisProjectionState
    progress: float
    stage: AnalysisStage | None
    latest_run: RunSummary | None
    published_run: RunSummary | None
    active_job: JobSummary | None
    failure: FailureSummary | None


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Safe artifact metadata reference without local paths."""

    artifact_id: str
    video_id: str
    analysis_run_id: str | None
    kind: str
    version: str
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactKindAvailability:
    """Availability and storage summary for one artifact kind."""

    kind: str
    count: int
    total_size_bytes: int
    latest_artifact_id: str


@dataclass(frozen=True, slots=True)
class ArtifactAvailabilitySummary:
    """Artifact availability grouped without exposing physical paths."""

    total_count: int
    total_size_bytes: int
    kinds: tuple[ArtifactKindAvailability, ...]
    references: tuple[ArtifactReference, ...]


@dataclass(frozen=True, slots=True)
class ShotTypeSummary:
    """Make/miss summary for a shot type."""

    shot_type: str
    attempts: int
    makes: int
    misses: int
    uncertain: int
    shooting_percentage: float | None


@dataclass(frozen=True, slots=True)
class PlayerSummary:
    """Make/miss summary for a video-local player track."""

    player_track_id: str | None
    display_name: str
    attempts: int
    makes: int
    misses: int
    uncertain: int
    shooting_percentage: float | None


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    """Review and confidence projection for effective attempts."""

    reviewed: int
    unreviewed: int
    review_required: int
    low_confidence: int
    corrected: int
    manual: int


@dataclass(frozen=True, slots=True)
class ShootingSummary:
    """Aggregate statistics derived from the published effective attempts."""

    attempts: int
    makes: int
    misses: int
    uncertain: int
    shooting_percentage: float | None
    review: ReviewSummary
    two_point: ShotTypeSummary
    three_point: ShotTypeSummary
    shot_types: tuple[ShotTypeSummary, ...]
    players: tuple[PlayerSummary, ...]


@dataclass(frozen=True, slots=True)
class VideoStorageSummary:
    """Per-video local storage usage."""

    original_size_bytes: int
    artifact_size_bytes: int
    total_size_bytes: int


@dataclass(frozen=True, slots=True)
class LibraryStorageSummary:
    """Whole-library local storage usage."""

    video_count: int
    original_size_bytes: int
    artifact_size_bytes: int
    total_size_bytes: int


@dataclass(frozen=True, slots=True)
class VideoCard:
    """Compact card projection for a video library dashboard."""

    video_id: str
    filename: str
    status: VideoStatus
    created_at: datetime
    activity_at: datetime
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str
    container: str
    analysis: AnalysisStatusSummary
    statistics: ShootingSummary | None
    artifacts: ArtifactAvailabilitySummary
    storage: VideoStorageSummary


@dataclass(frozen=True, slots=True)
class VideoDetail:
    """Detailed route-neutral projection for one video."""

    card: VideoCard
    runs: tuple[RunSummary, ...]
    jobs: tuple[JobSummary, ...]
    players: tuple[PlayerSummary, ...]
    artifacts: tuple[ArtifactReference, ...]


@dataclass(frozen=True, slots=True)
class VideoLibrary:
    """Full dashboard projection for all videos."""

    state: LibraryState
    videos: tuple[VideoCard, ...]
    storage: LibraryStorageSummary


class VideoLibraryService:
    """Read-only query service for video library dashboards and details."""

    def __init__(
        self,
        *,
        videos: VideoRepository,
        runs: AnalysisRunRepository,
        jobs: JobRepository,
        attempts: ShotAttemptRepository,
        artifacts: ArtifactRepository,
        players: PlayerTrackRepository,
        low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    ) -> None:
        if not 0 <= low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between zero and one")
        self._videos = videos
        self._runs = runs
        self._jobs = jobs
        self._attempts = attempts
        self._artifacts = artifacts
        self._players = players
        self._low_confidence_threshold = low_confidence_threshold

    def list_videos(self) -> VideoLibrary:
        """Return all video cards ordered by most recent activity."""
        cards = tuple(sorted((self._card(video) for video in self._videos.list()), key=_card_sort_key, reverse=True))
        storage = LibraryStorageSummary(
            video_count=len(cards),
            original_size_bytes=sum(card.storage.original_size_bytes for card in cards),
            artifact_size_bytes=sum(card.storage.artifact_size_bytes for card in cards),
            total_size_bytes=sum(card.storage.total_size_bytes for card in cards),
        )
        state = LibraryState.EMPTY if not cards else LibraryState.POPULATED
        return VideoLibrary(state=state, videos=cards, storage=storage)

    def get_video_detail(self, video_id: str) -> VideoDetail | None:
        """Return a detailed projection for one video, or ``None`` when deleted."""
        video = self._videos.get(video_id)
        if video is None:
            return None
        card = self._card(video)
        runs = tuple(_run_summary(run) for run in self._runs.list_for_video(video.id))
        jobs = tuple(_job_summary(job) for job in self._jobs.list_for_video(video.id))
        return VideoDetail(
            card=card,
            runs=runs,
            jobs=jobs,
            players=() if card.statistics is None else card.statistics.players,
            artifacts=card.artifacts.references,
        )

    def _card(self, video: Video) -> VideoCard:
        runs = self._runs.list_for_video(video.id)
        jobs = self._jobs.list_for_video(video.id)
        artifacts = self._artifacts.list_for_video(video.id)
        analysis = _analysis_summary(runs, jobs)
        statistics = self._statistics(video, analysis.published_run)
        availability = _artifact_availability(artifacts)
        storage = _storage_summary(video, artifacts)
        return VideoCard(
            video_id=video.id,
            filename=video.filename,
            status=video.status,
            created_at=video.created_at,
            activity_at=_activity_at(video, runs, jobs, artifacts),
            duration_seconds=video.duration_seconds,
            width=video.width,
            height=video.height,
            fps=video.fps,
            codec=video.codec,
            container=video.container,
            analysis=analysis,
            statistics=statistics,
            artifacts=availability,
            storage=storage,
        )

    def _statistics(self, video: Video, published_run: RunSummary | None) -> ShootingSummary | None:
        if published_run is None:
            return None
        attempts = tuple(attempt for attempt in self._attempts.list_effective(video.id) if not attempt.removed)
        players = {player.id: player for player in self._players.list_for_run(published_run.run_id)}
        return _shooting_summary(attempts, players, self._low_confidence_threshold)


def _card_sort_key(card: VideoCard) -> tuple[datetime, str]:
    return (card.activity_at, card.video_id)


def _analysis_summary(runs: Iterable[AnalysisRun], jobs: Iterable[AnalysisJob]) -> AnalysisStatusSummary:
    run_list = tuple(runs)
    job_list = tuple(jobs)
    active_job = _latest((job for job in job_list if job.status in (JobStatus.QUEUED, JobStatus.RUNNING)), _job_time)
    latest_job = _latest(job_list, _job_time)
    latest_run = _latest(run_list, _run_time)
    published_run = _latest((run for run in run_list if run.published), _run_time)
    active = None if active_job is None else _job_summary(active_job)
    latest = None if latest_run is None else _run_summary(latest_run)
    published = None if published_run is None else _run_summary(published_run)

    if active is not None:
        return AnalysisStatusSummary(
            state=_state_for_active_job(active.status),
            progress=active.progress,
            stage=active.stage,
            latest_run=latest,
            published_run=published,
            active_job=active,
            failure=active.failure,
        )
    if latest is None:
        return AnalysisStatusSummary(
            state=AnalysisProjectionState.NEVER_ANALYZED,
            progress=0.0,
            stage=None,
            latest_run=None,
            published_run=None,
            active_job=None,
            failure=None,
        )
    if latest_job is not None and latest_job.run_id == latest.run_id and latest_job.status is JobStatus.CANCELLED:
        cancelled_job = _job_summary(latest_job)
        return AnalysisStatusSummary(
            state=AnalysisProjectionState.CANCELLED,
            progress=cancelled_job.progress,
            stage=cancelled_job.stage,
            latest_run=latest,
            published_run=published,
            active_job=None,
            failure=cancelled_job.failure or latest.failure,
        )
    if latest.status is RunStatus.FAILED:
        return AnalysisStatusSummary(
            state=AnalysisProjectionState.FAILED,
            progress=latest.progress,
            stage=latest.stage,
            latest_run=latest,
            published_run=published,
            active_job=None,
            failure=latest.failure,
        )
    if latest.status is RunStatus.COMPLETED:
        return AnalysisStatusSummary(
            state=AnalysisProjectionState.COMPLETED,
            progress=latest.progress,
            stage=latest.stage,
            latest_run=latest,
            published_run=published,
            active_job=None,
            failure=None,
        )
    if published is not None:
        return AnalysisStatusSummary(
            state=AnalysisProjectionState.COMPLETED,
            progress=published.progress,
            stage=published.stage,
            latest_run=latest,
            published_run=published,
            active_job=None,
            failure=None,
        )
    return AnalysisStatusSummary(
        state=AnalysisProjectionState.RUNNING if latest.status is RunStatus.RUNNING else AnalysisProjectionState.QUEUED,
        progress=latest.progress,
        stage=latest.stage,
        latest_run=latest,
        published_run=None,
        active_job=None,
        failure=None,
    )


def _state_for_active_job(status: JobStatus) -> AnalysisProjectionState:
    if status is JobStatus.QUEUED:
        return AnalysisProjectionState.QUEUED
    if status is JobStatus.RUNNING:
        return AnalysisProjectionState.RUNNING
    if status is JobStatus.CANCELLED:
        return AnalysisProjectionState.CANCELLED
    if status is JobStatus.FAILED:
        return AnalysisProjectionState.FAILED
    return AnalysisProjectionState.COMPLETED


def _run_summary(run: AnalysisRun) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        started_at=run.started_at,
        completed_at=run.completed_at,
        backend_name=run.backend_name,
        published=run.published,
        failure=_failure_summary(run.error),
    )


def _job_summary(job: AnalysisJob) -> JobSummary:
    return JobSummary(
        job_id=job.id,
        run_id=job.run_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        created_at=job.created_at,
        updated_at=job.updated_at,
        failure=_failure_summary(job.error),
    )


def _failure_summary(error: JsonObject | None) -> FailureSummary | None:
    if error is None:
        return None
    category = _string_value(error, "category") or _string_value(error, "code") or "UNKNOWN"
    message = _string_value(error, "message") or category
    stage_value = _string_value(error, "stage")
    stage = None
    if stage_value is not None:
        try:
            stage = AnalysisStage(stage_value)
        except ValueError:
            stage = None
    return FailureSummary(category=category, message=message, stage=stage)


def _string_value(values: Mapping[str, JsonValue], key: str) -> str | None:
    value = values.get(key)
    return value if isinstance(value, str) else None


def _artifact_availability(artifacts: Iterable[Artifact]) -> ArtifactAvailabilitySummary:
    references = tuple(_artifact_reference(artifact) for artifact in artifacts)
    grouped: dict[str, list[ArtifactReference]] = defaultdict(list)
    for reference in references:
        grouped[reference.kind].append(reference)
    kinds = tuple(
        ArtifactKindAvailability(
            kind=kind,
            count=len(items),
            total_size_bytes=sum(item.size_bytes for item in items),
            latest_artifact_id=max(items, key=lambda item: (item.created_at, item.artifact_id)).artifact_id,
        )
        for kind, items in sorted(grouped.items())
    )
    return ArtifactAvailabilitySummary(
        total_count=len(references),
        total_size_bytes=sum(reference.size_bytes for reference in references),
        kinds=kinds,
        references=references,
    )


def _artifact_reference(artifact: Artifact) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=artifact.id,
        video_id=artifact.video_id,
        analysis_run_id=artifact.analysis_run_id,
        kind=artifact.kind,
        version=artifact.version,
        size_bytes=artifact.size_bytes,
        created_at=artifact.created_at,
    )


def _storage_summary(video: Video, artifacts: Iterable[Artifact]) -> VideoStorageSummary:
    artifact_size = sum(artifact.size_bytes for artifact in artifacts if artifact.id != video.original_artifact_id)
    total_size = video.size_bytes + artifact_size
    return VideoStorageSummary(
        original_size_bytes=video.size_bytes,
        artifact_size_bytes=artifact_size,
        total_size_bytes=total_size,
    )


def _activity_at(
    video: Video, runs: Iterable[AnalysisRun], jobs: Iterable[AnalysisJob], artifacts: Iterable[Artifact]
) -> datetime:
    moments = [video.created_at]
    for run in runs:
        moments.append(run.started_at)
        if run.completed_at is not None:
            moments.append(run.completed_at)
    for job in jobs:
        moments.append(job.created_at)
        moments.append(job.updated_at)
    for artifact in artifacts:
        moments.append(artifact.created_at)
    return max(moments)


def _shooting_summary(
    attempts: tuple[EffectiveShotAttempt, ...],
    players: Mapping[str, PlayerTrack],
    low_confidence_threshold: float,
) -> ShootingSummary:
    overall = _summary_counts(attempts)
    shot_types = _shot_type_summaries(attempts)
    player_summaries = _player_summaries(attempts, players)
    review_counter = Counter(attempt.review_status for attempt in attempts)
    review_required = sum(
        1
        for attempt in attempts
        if attempt.review_status is ReviewStatus.UNREVIEWED or attempt.outcome is ShotOutcome.UNCERTAIN
    )
    review = ReviewSummary(
        reviewed=review_counter[ReviewStatus.REVIEWED],
        unreviewed=review_counter[ReviewStatus.UNREVIEWED],
        review_required=review_required,
        low_confidence=sum(1 for attempt in attempts if attempt.automatic.confidence < low_confidence_threshold),
        corrected=sum(1 for attempt in attempts if _is_corrected(attempt)),
        manual=sum(1 for attempt in attempts if attempt.automatic.manual),
    )
    return ShootingSummary(
        attempts=overall.attempts,
        makes=overall.makes,
        misses=overall.misses,
        uncertain=overall.uncertain,
        shooting_percentage=overall.shooting_percentage,
        review=review,
        two_point=_summary_for_type(attempts, TWO_POINT_SHOT_TYPE),
        three_point=_summary_for_type(attempts, THREE_POINT_SHOT_TYPE),
        shot_types=shot_types,
        players=player_summaries,
    )


def _shot_type_summaries(attempts: tuple[EffectiveShotAttempt, ...]) -> tuple[ShotTypeSummary, ...]:
    shot_types = {attempt.shot_type for attempt in attempts}
    shot_types.update((TWO_POINT_SHOT_TYPE, THREE_POINT_SHOT_TYPE))
    return tuple(_summary_for_type(attempts, shot_type) for shot_type in sorted(shot_types, key=_shot_type_sort_key))


def _shot_type_sort_key(shot_type: str) -> tuple[int, str]:
    priority = {TWO_POINT_SHOT_TYPE: 0, THREE_POINT_SHOT_TYPE: 1}
    return (priority.get(shot_type, 2), shot_type)


def _summary_for_type(attempts: tuple[EffectiveShotAttempt, ...], shot_type: str) -> ShotTypeSummary:
    return _summary_counts(
        tuple(attempt for attempt in attempts if attempt.shot_type == shot_type), shot_type=shot_type
    )


def _player_summaries(
    attempts: tuple[EffectiveShotAttempt, ...],
    players: Mapping[str, PlayerTrack],
) -> tuple[PlayerSummary, ...]:
    by_player: dict[str | None, list[EffectiveShotAttempt]] = {player_id: [] for player_id in players}
    for attempt in attempts:
        by_player.setdefault(attempt.shooter_track_id, []).append(attempt)
    return tuple(
        _player_summary(player_id, tuple(group), players)
        for player_id, group in sorted(by_player.items(), key=lambda item: _player_sort_key(item[0], players))
    )


def _player_sort_key(player_id: str | None, players: Mapping[str, PlayerTrack]) -> tuple[str, str]:
    if player_id is None:
        return ("", "")
    player = players.get(player_id)
    return (player.display_name if player is not None else player_id, player_id)


def _player_summary(
    player_id: str | None,
    attempts: tuple[EffectiveShotAttempt, ...],
    players: Mapping[str, PlayerTrack],
) -> PlayerSummary:
    counts = _summary_counts(attempts)
    player = None if player_id is None else players.get(player_id)
    return PlayerSummary(
        player_track_id=player_id,
        display_name="Unknown player" if player is None else player.display_name,
        attempts=counts.attempts,
        makes=counts.makes,
        misses=counts.misses,
        uncertain=counts.uncertain,
        shooting_percentage=counts.shooting_percentage,
    )


def _summary_counts(attempts: tuple[EffectiveShotAttempt, ...], *, shot_type: str | None = None) -> ShotTypeSummary:
    attempts_count = len(attempts)
    makes = sum(1 for attempt in attempts if attempt.outcome is ShotOutcome.MADE)
    misses = sum(1 for attempt in attempts if attempt.outcome is ShotOutcome.MISSED)
    uncertain = sum(1 for attempt in attempts if attempt.outcome is ShotOutcome.UNCERTAIN)
    return ShotTypeSummary(
        shot_type=shot_type or "ALL",
        attempts=attempts_count,
        makes=makes,
        misses=misses,
        uncertain=uncertain,
        shooting_percentage=None if attempts_count == 0 else makes / attempts_count,
    )


def _is_corrected(attempt: EffectiveShotAttempt) -> bool:
    automatic = attempt.automatic
    return (
        attempt.shooter_track_id != automatic.shooter_track_id
        or attempt.outcome is not automatic.automatic_outcome
        or attempt.shot_type != automatic.shot_type
        or attempt.review_status is not automatic.review_status
    )


def _latest[T](items: Iterable[T], key: Callable[[T], SortKey]) -> T | None:
    values = tuple(items)
    if not values:
        return None
    return max(values, key=key)


def _run_time(run: AnalysisRun) -> tuple[datetime, str]:
    return (run.completed_at or run.started_at, run.id)


def _job_time(job: AnalysisJob) -> tuple[datetime, str]:
    return (job.updated_at, job.id)
