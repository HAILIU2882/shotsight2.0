"""Query tests for the read-only video library service."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    ShotAttempt,
    ShotLocation,
    ShotOutcome,
    Video,
    VideoStatus,
)
from shotsight2.domain.persistence import JsonObject
from shotsight2.services.video_library import AnalysisProjectionState, LibraryState, VideoLibraryService

NOW = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)


@dataclass(slots=True)
class _Repositories:
    videos: _VideoRepository
    runs: _RunRepository
    jobs: _JobRepository
    attempts: _AttemptRepository
    artifacts: _ArtifactRepository
    players: _PlayerRepository

    @property
    def write_calls(self) -> int:
        return (
            self.videos.write_calls
            + self.runs.write_calls
            + self.jobs.write_calls
            + self.attempts.write_calls
            + self.artifacts.write_calls
            + self.players.write_calls
        )


def test_empty_library_has_explicit_state_and_no_writes() -> None:
    """An empty database should project an explicit empty dashboard."""
    repositories = _repositories()
    service = _service(repositories)

    library = service.list_videos()

    assert library.state is LibraryState.EMPTY
    assert library.videos == ()
    assert library.storage.total_size_bytes == 0
    assert service.get_video_detail("deleted-video") is None
    assert repositories.write_calls == 0


def test_uploaded_video_is_never_analyzed_until_a_run_or_job_exists() -> None:
    """A plain uploaded video should not pretend analysis data is available."""
    uploaded = _video("video-uploaded", "upload.mov", created_at=NOW)
    repositories = _repositories(videos=[uploaded])
    service = _service(repositories)

    library = service.list_videos()
    detail = service.get_video_detail(uploaded.id)

    assert library.state is LibraryState.POPULATED
    assert len(library.videos) == 1
    card = library.videos[0]
    assert card.analysis.state is AnalysisProjectionState.NEVER_ANALYZED
    assert card.analysis.stage is None
    assert card.statistics is None
    assert card.storage.total_size_bytes == uploaded.size_bytes
    assert detail is not None
    assert detail.runs == ()
    assert detail.jobs == ()
    assert detail.artifacts == ()
    assert repositories.write_calls == 0


def test_query_projects_job_run_statuses_and_orders_by_recent_activity() -> None:
    """Queued, running, failed, and completed videos should sort by activity."""
    queued = _video("video-queued", "queued.mov", created_at=NOW + timedelta(minutes=1))
    running = _video("video-running", "running.mov", created_at=NOW + timedelta(minutes=2))
    failed = _video("video-failed", "failed.mov", created_at=NOW + timedelta(minutes=3))
    completed = _video("video-completed", "completed.mov", created_at=NOW + timedelta(minutes=4))
    deleting = _video(
        "video-deleting",
        "deleting.mov",
        created_at=NOW + timedelta(minutes=5),
        status=VideoStatus.DELETING,
    )
    cleanup_incomplete = _video(
        "video-cleanup",
        "cleanup.mov",
        created_at=NOW + timedelta(minutes=6),
        status=VideoStatus.CLEANUP_INCOMPLETE,
    )
    queued_run = _run(queued.id, "run-queued", RunStatus.PENDING, started_at=NOW + timedelta(minutes=7))
    running_run = _run(
        running.id,
        "run-running",
        RunStatus.RUNNING,
        started_at=NOW + timedelta(minutes=8),
        progress=0.42,
        stage=AnalysisStage.TRACKING,
    )
    failed_run = _run(
        failed.id,
        "run-failed",
        RunStatus.FAILED,
        started_at=NOW + timedelta(minutes=9),
        progress=0.55,
        stage=AnalysisStage.DETECTING_SHOTS,
        error={
            "category": "TRACKING_FAILED",
            "message": "Could not keep a stable ball track",
            "stage": AnalysisStage.TRACKING.value,
            "diagnostic_reference": "/unsafe/local/path.log",
        },
    )
    completed_run = _run(
        completed.id,
        "run-completed",
        RunStatus.COMPLETED,
        started_at=NOW + timedelta(minutes=10),
        completed_at=NOW + timedelta(minutes=11),
        progress=1.0,
        stage=AnalysisStage.FINALIZING,
        published=True,
    )
    queued_job = _job(queued.id, queued_run.id, "job-queued", JobStatus.QUEUED, updated_at=NOW + timedelta(minutes=12))
    running_job = _job(
        running.id,
        running_run.id,
        "job-running",
        JobStatus.RUNNING,
        updated_at=NOW + timedelta(minutes=13),
        progress=0.42,
        stage=AnalysisStage.TRACKING,
    )
    failed_job = _job(
        failed.id,
        failed_run.id,
        "job-failed",
        JobStatus.FAILED,
        updated_at=NOW + timedelta(minutes=14),
        progress=0.55,
        stage=AnalysisStage.TRACKING,
        error={"category": "TRACKING_FAILED", "message": "Worker stopped", "stage": AnalysisStage.TRACKING.value},
    )
    replay = _artifact(
        completed.id,
        completed_run.id,
        "artifact-replay",
        "REPLAY",
        size_bytes=2_000,
        created_at=NOW + timedelta(minutes=15),
    )
    tracked = _artifact(
        completed.id,
        completed_run.id,
        "artifact-tracked",
        "ANNOTATED_VIDEO",
        size_bytes=3_000,
        created_at=NOW + timedelta(minutes=16),
    )
    repositories = _repositories(
        videos=[queued, running, failed, completed, deleting, cleanup_incomplete],
        runs=[queued_run, running_run, failed_run, completed_run],
        jobs=[queued_job, running_job, failed_job],
        artifacts=[replay, tracked],
    )
    service = _service(repositories)

    library = service.list_videos()
    cards = {card.video_id: card for card in library.videos}

    assert [card.video_id for card in library.videos][:3] == [completed.id, failed.id, running.id]
    assert cards[queued.id].analysis.state is AnalysisProjectionState.QUEUED
    assert cards[queued.id].analysis.active_job is not None
    assert cards[running.id].analysis.state is AnalysisProjectionState.RUNNING
    assert cards[running.id].analysis.progress == 0.42
    assert cards[failed.id].analysis.state is AnalysisProjectionState.FAILED
    failure = cards[failed.id].analysis.failure
    assert failure is not None
    assert failure.category == "TRACKING_FAILED"
    assert failure.message == "Could not keep a stable ball track"
    assert cards[completed.id].analysis.state is AnalysisProjectionState.COMPLETED
    assert cards[completed.id].analysis.published_run is not None
    assert cards[completed.id].storage.artifact_size_bytes == 5_000
    assert cards[completed.id].artifacts.total_count == 2
    assert {kind.kind for kind in cards[completed.id].artifacts.kinds} == {"ANNOTATED_VIDEO", "REPLAY"}
    assert cards[deleting.id].status is VideoStatus.DELETING
    assert cards[cleanup_incomplete.id].status is VideoStatus.CLEANUP_INCOMPLETE
    assert library.storage.total_size_bytes == sum(card.storage.total_size_bytes for card in library.videos)
    assert repositories.write_calls == 0


def test_completed_video_attaches_corrected_statistics_and_safe_artifact_references() -> None:
    """Published effective attempts should drive stats without exposing local paths."""
    video = _video("video-completed", "final.mov", created_at=NOW)
    run = _run(
        video.id,
        "run-completed",
        RunStatus.COMPLETED,
        started_at=NOW + timedelta(minutes=1),
        completed_at=NOW + timedelta(minutes=2),
        progress=1.0,
        stage=AnalysisStage.FINALIZING,
        published=True,
    )
    player_one = _player(run.id, video.id, "player-1", "Ari")
    player_two = _player(run.id, video.id, "player-2", "Bo")
    made_correction = _effective_attempt(
        "attempt-1",
        run.id,
        "player-1",
        automatic_outcome=ShotOutcome.MISSED,
        outcome=ShotOutcome.MADE,
        automatic_shot_type="THREE_POINT",
        shot_type="TWO_POINT",
        review_status=ReviewStatus.REVIEWED,
        automatic_review_status=ReviewStatus.UNREVIEWED,
        confidence=0.92,
    )
    missed_low_confidence = _effective_attempt(
        "attempt-2",
        run.id,
        "player-2",
        automatic_outcome=ShotOutcome.MISSED,
        outcome=ShotOutcome.MISSED,
        automatic_shot_type="THREE_POINT",
        shot_type="THREE_POINT",
        review_status=ReviewStatus.UNREVIEWED,
        automatic_review_status=ReviewStatus.UNREVIEWED,
        confidence=0.35,
    )
    removed = _effective_attempt(
        "attempt-removed",
        run.id,
        "player-1",
        automatic_outcome=ShotOutcome.MADE,
        outcome=ShotOutcome.MADE,
        automatic_shot_type="TWO_POINT",
        shot_type="TWO_POINT",
        review_status=ReviewStatus.REVIEWED,
        automatic_review_status=ReviewStatus.REVIEWED,
        confidence=0.99,
        removed=True,
    )
    replay = _artifact(
        video.id,
        run.id,
        "replay-1",
        "REPLAY",
        size_bytes=4_096,
        created_at=NOW + timedelta(minutes=3),
        logical_path="/Users/hailiu/private/full/path/replay.mp4",
    )
    repositories = _repositories(
        videos=[video],
        runs=[run],
        attempts={video.id: [made_correction, missed_low_confidence, removed]},
        artifacts=[replay],
        players=[player_one, player_two],
    )
    service = _service(repositories)

    detail = service.get_video_detail(video.id)

    assert detail is not None
    statistics = detail.card.statistics
    assert statistics is not None
    assert statistics.attempts == 2
    assert statistics.makes == 1
    assert statistics.misses == 1
    assert statistics.shooting_percentage == 0.5
    assert statistics.review.reviewed == 1
    assert statistics.review.unreviewed == 1
    assert statistics.review.review_required == 1
    assert statistics.review.low_confidence == 1
    assert statistics.review.corrected == 1
    assert statistics.two_point.attempts == 1
    assert statistics.two_point.makes == 1
    assert statistics.three_point.attempts == 1
    assert statistics.three_point.misses == 1
    assert [(player.display_name, player.attempts, player.makes) for player in statistics.players] == [
        ("Ari", 1, 1),
        ("Bo", 1, 0),
    ]
    assert detail.artifacts[0].artifact_id == replay.id
    assert detail.artifacts[0].kind == "REPLAY"
    assert not hasattr(detail.artifacts[0], "logical_path")
    assert repositories.write_calls == 0


def _repositories(
    *,
    videos: Iterable[Video] = (),
    runs: Iterable[AnalysisRun] = (),
    jobs: Iterable[AnalysisJob] = (),
    attempts: dict[str, list[EffectiveShotAttempt]] | None = None,
    artifacts: Iterable[Artifact] = (),
    players: Iterable[PlayerTrack] = (),
) -> _Repositories:
    return _Repositories(
        videos=_VideoRepository(videos),
        runs=_RunRepository(runs),
        jobs=_JobRepository(jobs),
        attempts=_AttemptRepository(attempts or {}),
        artifacts=_ArtifactRepository(artifacts),
        players=_PlayerRepository(players),
    )


def _service(repositories: _Repositories) -> VideoLibraryService:
    return VideoLibraryService(
        videos=repositories.videos,
        runs=repositories.runs,
        jobs=repositories.jobs,
        attempts=repositories.attempts,
        artifacts=repositories.artifacts,
        players=repositories.players,
    )


class _VideoRepository:
    def __init__(self, videos: Iterable[Video]) -> None:
        self._videos = {video.id: video for video in videos}
        self.write_calls = 0

    def create(self, video: Video) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not write videos")

    def get(self, video_id: str) -> Video | None:
        return self._videos.get(video_id)

    def list(self) -> list[Video]:
        return list(self._videos.values())

    def mark_deleting(self, video_id: str) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not mark videos deleting")

    def delete(self, video_id: str) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not delete videos")


class _RunRepository:
    def __init__(self, runs: Iterable[AnalysisRun]) -> None:
        self._runs = {run.id: run for run in runs}
        self.write_calls = 0

    def create(self, run: AnalysisRun) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not write runs")

    def get(self, run_id: str) -> AnalysisRun | None:
        return self._runs.get(run_id)

    def list_for_video(self, video_id: str, *, published_only: bool = False) -> list[AnalysisRun]:
        return [
            run for run in self._runs.values() if run.video_id == video_id and (not published_only or run.published)
        ]

    def update_progress(self, run_id: str, progress: float, stage: AnalysisStage) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not update runs")

    def fail(self, run_id: str, error: JsonObject) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not fail runs")

    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not publish runs")


class _JobRepository:
    def __init__(self, jobs: Iterable[AnalysisJob]) -> None:
        self._jobs = {job.id: job for job in jobs}
        self.write_calls = 0

    def create(self, job: AnalysisJob) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not write jobs")

    def get(self, job_id: str) -> AnalysisJob | None:
        return self._jobs.get(job_id)

    def list_for_video(self, video_id: str) -> list[AnalysisJob]:
        return [job for job in self._jobs.values() if job.video_id == video_id]

    def list_active(self) -> list[AnalysisJob]:
        return [job for job in self._jobs.values() if job.status in (JobStatus.QUEUED, JobStatus.RUNNING)]

    def update_state(
        self,
        job_id: str,
        status: JobStatus,
        stage: AnalysisStage,
        progress: float,
        *,
        error: JsonObject | None = None,
    ) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not update jobs")


class _AttemptRepository:
    def __init__(self, attempts: dict[str, list[EffectiveShotAttempt]]) -> None:
        self._attempts = attempts
        self.write_calls = 0

    def replace_automatic_results(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
    ) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not replace attempts")

    def list_for_run(self, run_id: str) -> list[ShotAttempt]:
        return []

    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]:
        return list(self._attempts.get(video_id, ()))


class _ArtifactRepository:
    def __init__(self, artifacts: Iterable[Artifact]) -> None:
        self._artifacts = list(artifacts)
        self.write_calls = 0

    def add(self, artifact: Artifact) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not write artifacts")

    def list_for_run(self, run_id: str) -> list[Artifact]:
        return [artifact for artifact in self._artifacts if artifact.analysis_run_id == run_id]

    def list_for_video(self, video_id: str) -> list[Artifact]:
        return [artifact for artifact in self._artifacts if artifact.video_id == video_id]


class _PlayerRepository:
    def __init__(self, players: Iterable[PlayerTrack]) -> None:
        self._players = list(players)
        self.write_calls = 0

    def replace_for_run(self, run_id: str, tracks: Sequence[PlayerTrack]) -> None:
        self.write_calls += 1
        raise AssertionError("video library queries must not replace players")

    def list_for_run(self, run_id: str) -> list[PlayerTrack]:
        return [player for player in self._players if player.analysis_run_id == run_id]

    def list_for_video(self, video_id: str) -> list[PlayerTrack]:
        return [player for player in self._players if player.video_id == video_id]

    def rename_display_name(self, player_track_id: str, display_name: str) -> None:
        del player_track_id, display_name
        self.write_calls += 1
        raise AssertionError("video library queries must not rename players")


def _video(
    video_id: str,
    filename: str,
    *,
    created_at: datetime,
    status: VideoStatus = VideoStatus.READY,
) -> Video:
    return Video(
        id=video_id,
        filename=filename,
        original_artifact_id=f"{video_id}-original",
        size_bytes=1_000,
        duration_seconds=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        container="mp4",
        created_at=created_at,
        status=status,
    )


def _run(
    video_id: str,
    run_id: str,
    status: RunStatus,
    *,
    started_at: datetime,
    progress: float = 0.0,
    stage: AnalysisStage = AnalysisStage.VALIDATING,
    completed_at: datetime | None = None,
    error: JsonObject | None = None,
    published: bool = False,
) -> AnalysisRun:
    return AnalysisRun(
        id=run_id,
        video_id=video_id,
        status=status,
        backend_name="fake-backend",
        backend_version="1.0",
        configuration={"profile": "balanced"},
        progress=progress,
        stage=stage,
        started_at=started_at,
        completed_at=completed_at,
        error=error,
        published=published,
    )


def _job(
    video_id: str,
    run_id: str,
    job_id: str,
    status: JobStatus,
    *,
    updated_at: datetime,
    progress: float = 0.0,
    stage: AnalysisStage = AnalysisStage.VALIDATING,
    error: JsonObject | None = None,
) -> AnalysisJob:
    return AnalysisJob(
        id=job_id,
        video_id=video_id,
        run_id=run_id,
        status=status,
        stage=stage,
        progress=progress,
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
        error=error,
    )


def _player(run_id: str, video_id: str, player_id: str, display_name: str) -> PlayerTrack:
    return PlayerTrack(
        id=player_id,
        analysis_run_id=run_id,
        video_id=video_id,
        local_label=display_name,
        display_name=display_name,
        confidence=0.9,
    )


def _artifact(
    video_id: str,
    run_id: str,
    artifact_id: str,
    kind: str,
    *,
    size_bytes: int,
    created_at: datetime,
    logical_path: str | None = None,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        video_id=video_id,
        analysis_run_id=run_id,
        kind=kind,
        logical_path=logical_path or f"{video_id}/{run_id}/{artifact_id}.mp4",
        version="v1",
        size_bytes=size_bytes,
        created_at=created_at,
    )


def _effective_attempt(
    attempt_id: str,
    run_id: str,
    shooter_track_id: str,
    *,
    automatic_outcome: ShotOutcome,
    outcome: ShotOutcome,
    automatic_shot_type: str,
    shot_type: str,
    automatic_review_status: ReviewStatus,
    review_status: ReviewStatus,
    confidence: float,
    removed: bool = False,
) -> EffectiveShotAttempt:
    automatic = ShotAttempt(
        id=attempt_id,
        analysis_run_id=run_id,
        shooter_track_id=shooter_track_id,
        release_seconds=1.0,
        automatic_outcome=automatic_outcome,
        shot_type=automatic_shot_type,
        confidence=confidence,
        review_status=automatic_review_status,
        evidence={"frame": 30},
    )
    return EffectiveShotAttempt(
        automatic=automatic,
        shooter_track_id=shooter_track_id,
        outcome=outcome,
        shot_type=shot_type,
        review_status=review_status,
        location=None,
        removed=removed,
    )
