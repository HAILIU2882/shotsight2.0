"""Real local worker integration for the production analysis pipeline."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotsight2.adapters.ffmpeg import FFmpegAdapter
from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDatabase,
    SQLiteJobRepository,
    SQLiteShotAttemptRepository,
    SQLiteVideoRepository,
)
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.persistence import (
    Artifact,
    JobStatus,
    RunStatus,
    ShotAttempt,
    ShotLocation,
    Video,
    VideoStatus,
)
from shotsight2.services.analysis_jobs import AnalysisConfiguration, AnalysisJobService
from shotsight2.services.video_ingestion import UploadVideoCommand, VideoIngestionService
from shotsight2.worker.process import WorkerProcess
from shotsight2.worker.runtime import create_production_handler

NOW = datetime(2026, 6, 20, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def require_media_tools() -> None:
    """Skip the process-level smoke when the host has no FFmpeg toolchain."""

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required for production pipeline integration")


def test_production_worker_runs_real_stages_and_publishes_outputs(tmp_path: Path) -> None:
    """A claimed upload reaches a published run through real local adapters."""

    runtime = _runtime(tmp_path)
    source = _generated_video(tmp_path / "source-a.mp4", width=160, height=90, color="darkgreen")
    video = _ingest(runtime, source, "video-a")
    snapshot = runtime.jobs.request_analysis(video.id, _configuration())

    runtime.worker("success-worker").run(once=True)

    job = runtime.job_repository.get(snapshot.job.id)
    run = runtime.run_repository.get(snapshot.run.id)
    assert job is not None and job.status is JobStatus.COMPLETED
    assert run is not None and run.status is RunStatus.COMPLETED and run.published
    assert run.progress == 1.0
    assert runtime.run_repository.list_for_video(video.id, published_only=True) == [run]
    assert runtime.attempt_repository.list_for_run(run.id) == []

    segments = runtime.segment_repository.list_for_run(run.id)
    assert segments
    assert any(item.stability_status == "STABLE" for item in segments)
    assert all(item.analysis_run_id == run.id for item in segments)

    artifacts = runtime.artifact_repository.list_for_run(run.id)
    kinds = {item.kind for item in artifacts}
    assert {"ANALYSIS_PROXY", "TRACK_DATA", "ANNOTATED_VIDEO", "RENDER_METADATA"} <= kinds
    annotated = next(item for item in artifacts if item.kind == "ANNOTATED_VIDEO")
    with runtime.store.local_path(ArtifactId(f"run:{annotated.logical_path}")) as rendered:
        metadata = runtime.media.probe(rendered)
    assert metadata.video.display_width == 160
    assert metadata.video.display_height == 90
    assert metadata.duration_seconds == pytest.approx(2.4, abs=0.25)


def test_production_worker_failure_settles_job_and_run_once(tmp_path: Path) -> None:
    """A validation failure leaves both durable records failed without claim loss."""

    runtime = _runtime(tmp_path)
    video_id = "video-corrupt"
    source_id = runtime.store.original_id(video_id, "mp4")
    runtime.store.write_atomic(source_id, (b"not a video",))
    runtime.video_repository.create(
        Video(
            id=video_id,
            filename="corrupt.mp4",
            original_artifact_id=str(source_id),
            size_bytes=11,
            duration_seconds=1.0,
            width=64,
            height=64,
            fps=10.0,
            codec="unknown",
            container="mp4",
            created_at=NOW,
            status=VideoStatus.READY,
        )
    )
    snapshot = runtime.jobs.request_analysis(video_id, _configuration())

    runtime.worker("failure-worker").run(once=True)

    job = runtime.job_repository.get(snapshot.job.id)
    run = runtime.run_repository.get(snapshot.run.id)
    assert job is not None and job.status is JobStatus.FAILED
    assert run is not None and run.status is RunStatus.FAILED and not run.published
    assert job.error is not None and job.error["type"] == "PipelineExecutionError"
    assert run.error is not None and run.error["stage"] == "VALIDATING"


def test_two_jobs_read_their_own_uploaded_media(tmp_path: Path) -> None:
    """Sequential jobs render dimensions from their own upload, never global media."""

    runtime = _runtime(tmp_path)
    sources = (
        _generated_video(tmp_path / "first.mp4", width=160, height=90, color="navy"),
        _generated_video(tmp_path / "second.mp4", width=128, height=96, color="maroon"),
    )
    expected = ((160, 90), (128, 96))
    observed: list[tuple[int, int]] = []

    for index, source in enumerate(sources, start=1):
        video = _ingest(runtime, source, f"video-{index}")
        snapshot = runtime.jobs.request_analysis(video.id, _configuration())
        runtime.worker(f"media-worker-{index}").run(once=True)
        run = runtime.run_repository.get(snapshot.run.id)
        assert run is not None and run.published
        artifacts = runtime.artifact_repository.list_for_run(run.id)
        annotated = next(item for item in artifacts if item.kind == "ANNOTATED_VIDEO")
        with runtime.store.local_path(ArtifactId(f"run:{annotated.logical_path}")) as rendered:
            metadata = runtime.media.probe(rendered)
        observed.append((metadata.video.display_width, metadata.video.display_height))

    assert tuple(observed) == expected


def test_publication_failure_compensates_promoted_run_outputs(tmp_path: Path) -> None:
    """A post-render publication failure removes every non-diagnostic run file."""

    runtime = _runtime(tmp_path)
    source = _generated_video(tmp_path / "rollback.mp4", width=144, height=80, color="purple")
    video = _ingest(runtime, source, "video-rollback")
    snapshot = runtime.jobs.request_analysis(video.id, _configuration())
    handler = create_production_handler(
        database=runtime.database,
        data_dir=runtime.data_dir,
        publisher=_FailingPublisher(),
    )

    runtime.worker("rollback-worker", handler=handler).run(once=True)

    job = runtime.job_repository.get(snapshot.job.id)
    run = runtime.run_repository.get(snapshot.run.id)
    assert job is not None and job.status is JobStatus.FAILED
    assert run is not None and run.status is RunStatus.FAILED and not run.published
    assert runtime.artifact_repository.list_for_run(run.id) == []
    inventory = runtime.store.inventory_for_video(video.id)
    assert tuple(str(item.artifact_id) for item in inventory.artifacts) == (video.original_artifact_id,)


class _FailingPublisher:
    """Fail only after every concrete stage has generated its outputs."""

    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None:
        del run_id, attempts, locations, artifacts
        raise OSError("injected publication failure")


class _Runtime:
    """Isolated concrete runtime shared by one integration test."""

    def __init__(self, root: Path) -> None:
        self.data_dir = root / "data"
        self.database = SQLiteDatabase(root / "shotsight2.db")
        self.database.migrate()
        self.store = FileSystemArtifactStore(ArtifactStoreRoots.under(self.data_dir))
        self.media = FFmpegAdapter()
        self.video_repository = SQLiteVideoRepository(self.database)
        self.run_repository = SQLiteAnalysisRunRepository(self.database)
        self.job_repository = SQLiteJobRepository(self.database)
        self.segment_repository = SQLiteCameraSegmentRepository(self.database)
        self.artifact_repository = SQLiteArtifactRepository(self.database)
        self.attempt_repository = SQLiteShotAttemptRepository(self.database)
        self.queue = SQLiteWorkerQueue(self.database)
        self.jobs = AnalysisJobService(
            videos=self.video_repository,
            runs=self.run_repository,
            jobs=self.job_repository,
            queue=self.queue,
        )
        self.handler = create_production_handler(database=self.database, data_dir=self.data_dir)

    def worker(
        self,
        worker_id: str,
        *,
        handler: Callable[[QueueMessage], None] | None = None,
    ) -> WorkerProcess:
        return WorkerProcess(self.queue, handler or self.handler, worker_id=worker_id)


def _runtime(tmp_path: Path) -> _Runtime:
    return _Runtime(tmp_path)


def _configuration() -> AnalysisConfiguration:
    return AnalysisConfiguration(
        backend_name="opencv-cpu",
        backend_version="integration",
        values={"proxy_profile": "speed", "tracking_fps": 5.0},
    )


def _ingest(runtime: _Runtime, source: Path, identifier: str) -> Video:
    service = VideoIngestionService(
        media_tool=runtime.media,
        video_repository=runtime.video_repository,
        artifact_store=runtime.store,
        id_factory=lambda: identifier,
        clock=lambda: NOW,
    )
    return service.ingest(UploadVideoCommand(filename=source.name, chunks=_chunks(source))).video


def _chunks(path: Path, size: int = 4096) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(size):
            yield chunk


def _generated_video(
    destination: Path,
    *,
    width: int,
    height: int,
    color: str,
) -> Path:
    filter_graph = (
        f"color=c={color}:s={width}x{height}:r=10:d=2.4,drawbox=x=8:y=8:w={width - 16}:h={height - 16}:color=white:t=2"
    )
    completed = subprocess.run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            filter_graph,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ),
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr
    return destination
