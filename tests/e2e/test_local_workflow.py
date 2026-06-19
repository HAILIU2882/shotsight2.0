"""Release-gate test for the local upload, analysis, review, reanalysis, and deletion workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteDatabase,
    SQLiteDeletionRepository,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteShotAttemptRepository,
    SQLiteVideoRepository,
)
from shotsight2.domain import AnalysisStage, JobStatus, PlayerTrack, ReviewStatus, RunStatus, ShotAttempt, ShotLocation
from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.media import (
    AudioStreamMetadata,
    ClipRequest,
    ClipResult,
    EncodeResult,
    FrameExtractionRequest,
    FrameExtractionResult,
    MediaMetadata,
    MediaToolStatus,
    OverlayEncodeRequest,
    ProxyRequest,
    ProxyResult,
    RenderedFramesEncodeRequest,
    ToolStatus,
    VideoStreamMetadata,
)
from shotsight2.domain.persistence import JsonObject, ShotOutcome
from shotsight2.ports.jobs import WorkerQueue
from shotsight2.services import AnalysisConfiguration, AnalysisJobService, StatisticsService
from shotsight2.services.deletion import VideoDeletionService
from shotsight2.services.review import ReviewService
from shotsight2.services.video_ingestion import UploadVideoCommand, VideoIngestionService

NOW = datetime(2026, 6, 19, 8, 0, tzinfo=UTC)


class RecordingQueue(WorkerQueue):
    """Small queue fake that records enqueued analysis work."""

    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []

    def enqueue(self, message: QueueMessage, *, enqueued_at: datetime) -> bool:
        self.messages.append(message)
        return True

    def claim(self, worker_id: str, *, claimed_at: datetime, stale_after: timedelta) -> None:
        raise NotImplementedError

    def acknowledge(self, claim: object, *, acknowledged_at: datetime) -> None:
        raise NotImplementedError

    def fail(self, claim: object, error: JsonObject, *, failed_at: datetime) -> None:
        raise NotImplementedError

    def heartbeat(self, worker_id: str, *, heartbeat_at: datetime, job_id: str | None = None) -> None:
        raise NotImplementedError

    def stop_worker(self, worker_id: str, *, stopped_at: datetime) -> None:
        raise NotImplementedError

    def is_worker_alive(self, worker_id: str, *, checked_at: datetime, stale_after: timedelta) -> bool:
        return False


class FakeMediaTool:
    """Media adapter fake used only to probe uploaded bytes deterministically."""

    def status(self) -> MediaToolStatus:
        tool = ToolStatus("fake", True, Path("/fake/tool"), "fake")
        return MediaToolStatus(ffmpeg=tool, ffprobe=tool)

    def probe(self, source: Path) -> MediaMetadata:
        return _metadata(source)

    def create_proxy(self, request: ProxyRequest) -> ProxyResult:
        raise NotImplementedError

    def extract_frame(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        raise NotImplementedError

    def create_clip(self, request: ClipRequest) -> ClipResult:
        raise NotImplementedError

    def encode_rendered_frames(self, request: RenderedFramesEncodeRequest) -> EncodeResult:
        raise NotImplementedError

    def encode_overlay(self, request: OverlayEncodeRequest) -> EncodeResult:
        raise NotImplementedError


def test_local_upload_analysis_review_reanalysis_and_deletion_workflow(tmp_path: Path) -> None:
    """Exercise the core local workflow with real SQLite repositories and artifact storage."""

    database = SQLiteDatabase(tmp_path / "shotsight2.db")
    database.migrate()
    artifact_store = FileSystemArtifactStore(ArtifactStoreRoots.under(tmp_path / "data"))

    videos = SQLiteVideoRepository(database)
    runs = SQLiteAnalysisRunRepository(database)
    jobs = SQLiteJobRepository(database)
    players = SQLitePlayerTrackRepository(database)
    attempts = SQLiteShotAttemptRepository(database)
    corrections = SQLiteReviewCorrectionRepository(database)
    artifact_records = SQLiteArtifactRepository(database)
    deletion_records = SQLiteDeletionRepository(database)
    queue = RecordingQueue()
    ids = iter(("run-1", "job-1", "run-2", "job-2"))

    ingestion = VideoIngestionService(
        media_tool=FakeMediaTool(),
        video_repository=videos,
        artifact_store=artifact_store,
        id_factory=lambda: "e2e",
        clock=lambda: NOW,
    )
    analysis = AnalysisJobService(
        videos=videos,
        runs=runs,
        jobs=jobs,
        queue=queue,
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    statistics = StatisticsService(attempts, players)
    review = ReviewService(corrections, attempts, players, statistics, id_factory=_id_sequence("correction"))
    deletion = VideoDeletionService(
        videos=videos,
        deletion=deletion_records,
        artifacts=artifact_records,
        artifact_store=artifact_store,
    )

    uploaded = ingestion.ingest(UploadVideoCommand("session.mov", [b"fake", b"-video"]))
    video_id = uploaded.video.id

    first = analysis.request_analysis(video_id, _config())
    assert queue.messages == [QueueMessage("job-1", video_id, "run-1")]
    analysis.mark_running(first.job.id)
    analysis.update_progress(first.job.id, AnalysisStage.RENDERING_ARTIFACTS, 0.8)
    players.replace_for_run("run-1", (_player("run-1", video_id),))
    runs.publish_completed("run-1", [_attempt("attempt-1", "run-1")], [_location("attempt-1")], [])
    analysis.mark_completed(first.job.id)

    first_job = jobs.get("job-1")
    first_run = runs.get("run-1")
    assert first_job is not None
    assert first_run is not None
    assert first_job.status is JobStatus.COMPLETED
    assert first_run.status is RunStatus.COMPLETED
    assert attempts.list_effective(video_id)[0].outcome is ShotOutcome.MISSED

    reviewed_stats = review.override_outcome(video_id, "attempt-1", ShotOutcome.MADE, NOW)
    review.rename_player("player-run-1", "Alice")
    assert reviewed_stats.totals.makes == 1
    effective = attempts.list_effective(video_id)[0]
    assert effective.outcome is ShotOutcome.MADE
    assert effective.review_status is ReviewStatus.REVIEWED
    assert players.list_for_video(video_id)[0].display_name == "Alice"

    second = analysis.request_reanalysis(video_id, _config())
    assert queue.messages[-1] == QueueMessage("job-2", video_id, "run-2")
    analysis.mark_running(second.job.id)
    players.replace_for_run("run-2", (_player("run-2", video_id),))
    runs.publish_completed(
        "run-2",
        [_attempt("attempt-2", "run-2", outcome=ShotOutcome.MADE)],
        [_location("attempt-2")],
        [],
    )
    analysis.mark_completed(second.job.id)

    published_runs = runs.list_for_video(video_id, published_only=True)
    assert [run.id for run in published_runs] == ["run-2"]
    assert [item.automatic.id for item in attempts.list_effective(video_id)] == ["attempt-2"]

    inventory = deletion.build_inventory(video_id)
    assert inventory.video is not None
    assert inventory.filesystem_artifacts.total_bytes == uploaded.bytes_written

    deleted = deletion.delete_video(video_id)

    assert deleted.status.value == "DELETED"
    assert videos.get(video_id) is None
    assert runs.list_for_video(video_id) == []
    assert artifact_store.inventory_for_video(video_id).artifacts == ()


def _config() -> AnalysisConfiguration:
    return AnalysisConfiguration("opencv-cpu", "test", {"sample_fps": 10})


def _id_sequence(prefix: str) -> Callable[[], str]:
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-{counter}"

    return next_id


def _player(run_id: str, video_id: str) -> PlayerTrack:
    return PlayerTrack(
        id=f"player-{run_id}",
        analysis_run_id=run_id,
        video_id=video_id,
        local_label="Player 1",
        display_name="Player 1",
        confidence=0.95,
    )


def _attempt(attempt_id: str, run_id: str, *, outcome: ShotOutcome = ShotOutcome.MISSED) -> ShotAttempt:
    return ShotAttempt(
        id=attempt_id,
        analysis_run_id=run_id,
        shooter_track_id=f"player-{run_id}",
        release_seconds=12.0,
        automatic_outcome=outcome,
        shot_type="TWO_POINT",
        confidence=0.88,
        review_status=ReviewStatus.UNREVIEWED,
        evidence={"source": "e2e"},
    )


def _location(attempt_id: str) -> ShotLocation:
    return ShotLocation(
        id=f"location-{attempt_id}",
        shot_attempt_id=attempt_id,
        court_x_m=1.0,
        court_y_m=2.0,
        normalized_x=0.45,
        normalized_y=0.55,
        region="PAINT",
        indicative=False,
    )


def _metadata(path: Path) -> MediaMetadata:
    return MediaMetadata(
        path=path,
        format_name="mp4",
        duration_seconds=30.0,
        size_bytes=path.stat().st_size,
        bit_rate_bps=None,
        video=VideoStreamMetadata(
            stream_index=0,
            codec="h264",
            width=1280,
            height=720,
            display_width=1280,
            display_height=720,
            average_fps=30.0,
            nominal_fps=30.0,
            pixel_format="yuv420p",
            rotation_degrees=0,
            frame_count=900,
            is_variable_frame_rate=False,
        ),
        audio_streams=(AudioStreamMetadata(1, "aac", 48_000, 2),),
    )
