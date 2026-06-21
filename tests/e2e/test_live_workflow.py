"""Combined release gate for the real local HTTP and worker workflow."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteJobRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteShotAttemptRepository,
    SQLiteVideoRepository,
)
from shotsight2.config import Settings
from shotsight2.domain.persistence import JobStatus, ReviewStatus, RunStatus, ShotOutcome
from shotsight2.main import LocalRuntime, create_app
from shotsight2.worker.process import WorkerProcess
from shotsight2.worker.runtime import create_production_handler


@pytest.fixture(autouse=True)
def require_media_tools() -> None:
    """Skip the release gate when the real local FFmpeg toolchain is absent."""

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required for the combined release gate")


def test_live_upload_analysis_review_reanalysis_and_deletion(tmp_path: Path) -> None:
    """Exercise the complete local product workflow through presentation routes."""

    settings = _settings(tmp_path)
    app = create_app(settings)
    runtime: LocalRuntime = app.state.runtime
    videos = SQLiteVideoRepository(runtime.database)
    runs = SQLiteAnalysisRunRepository(runtime.database)
    jobs = SQLiteJobRepository(runtime.database)
    attempts = SQLiteShotAttemptRepository(runtime.database)
    corrections = SQLiteReviewCorrectionRepository(runtime.database)
    artifacts = SQLiteArtifactRepository(runtime.database)
    source = _generated_no_shot_video(tmp_path / "release-gate.mp4")

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        initial_readiness = client.get("/ready")
        assert initial_readiness.status_code == 503
        assert initial_readiness.json()["worker"]["status"] == "missing"

        upload = client.post(
            "/upload",
            files={"file": (source.name, source.read_bytes(), "video/mp4")},
            follow_redirects=False,
        )
        assert upload.status_code == 303
        location = upload.headers["location"]
        assert location.startswith("/videos/")
        assert not upload.headers.get("content-type", "").startswith("application/json")
        detail = client.get(location)
        assert detail.status_code == 200
        assert detail.headers["content-type"].startswith("text/html")
        assert source.name in detail.text

        video_id = urlparse(location).path.removeprefix("/videos/")
        uploaded = videos.get(video_id)
        assert uploaded is not None
        upload_inventory = runtime.artifact_store.inventory_for_video(video_id)
        assert len(upload_inventory.artifacts) == 1

        runtime.worker_queue.heartbeat("readiness-worker", heartbeat_at=datetime.now(UTC))
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["worker"]["status"] == "ready"

        analysis = client.post(
            f"/videos/{video_id}/analyze",
            data={"backend_name": "opencv-cpu", "backend_version": "release-gate"},
            follow_redirects=False,
        )
        assert analysis.status_code == 303
        first_job_id = jobs.list_for_video(video_id)[0].id
        _run_worker(runtime, settings.data_dir, "release-worker-1")

        first_job = jobs.get(first_job_id)
        first_run = runs.get(first_job.run_id) if first_job is not None else None
        assert first_job is not None and first_job.status is JobStatus.COMPLETED
        assert first_run is not None and first_run.status is RunStatus.COMPLETED
        assert first_run.published
        assert attempts.list_for_run(first_run.id) == []
        first_artifacts = artifacts.list_for_run(first_run.id)
        assert {artifact.kind for artifact in first_artifacts} >= {
            "ANALYSIS_PROXY",
            "ANNOTATED_VIDEO",
            "TRACK_DATA",
            "RENDER_METADATA",
        }

        create_attempt = client.post(
            f"/videos/{video_id}/attempts/create",
            data={
                "run_id": first_run.id,
                "release_seconds": "1.0",
                "shot_type": "TWO_POINT",
                "outcome": "MISSED",
            },
            follow_redirects=False,
        )
        assert create_attempt.status_code == 303
        manual_attempt = attempts.list_for_run(first_run.id)[0]
        assert manual_attempt.manual
        assert manual_attempt.automatic_outcome is ShotOutcome.MISSED

        update_attempt = client.post(
            f"/videos/{video_id}/attempts/{manual_attempt.id}/update",
            data={"outcome": "MADE", "shot_type": "TWO_POINT", "shooter_track_id": ""},
            follow_redirects=False,
        )
        assert update_attempt.status_code == 303
        effective = attempts.list_effective(video_id)
        assert len(effective) == 1
        assert effective[0].outcome is ShotOutcome.MADE
        assert effective[0].review_status is ReviewStatus.REVIEWED
        first_corrections = corrections.list_for_attempt(manual_attempt.id)
        assert first_corrections

        reanalysis = client.post(
            f"/videos/{video_id}/reanalyze",
            data={"backend_name": "opencv-cpu", "backend_version": "release-gate"},
            follow_redirects=False,
        )
        assert reanalysis.status_code == 303
        second_job = next(job for job in jobs.list_for_video(video_id) if job.id != first_job.id)
        _run_worker(runtime, settings.data_dir, "release-worker-2")

        completed_runs = runs.list_for_video(video_id)
        second_job_record = jobs.get(second_job.id)
        second_run = runs.get(second_job.run_id)
        preserved_first = runs.get(first_run.id)
        assert len(completed_runs) == 2
        assert all(run.status is RunStatus.COMPLETED for run in completed_runs)
        assert second_job_record is not None and second_job_record.status is JobStatus.COMPLETED
        assert second_run is not None and second_run.published
        assert preserved_first is not None and not preserved_first.published
        assert attempts.list_for_run(first_run.id) == [manual_attempt]
        assert corrections.list_for_attempt(manual_attempt.id) == first_corrections
        assert artifacts.list_for_run(first_run.id) == first_artifacts
        assert attempts.list_for_run(second_run.id) == []
        assert attempts.list_effective(video_id) == []
        runtime.worker_queue.stop_worker("readiness-worker", stopped_at=datetime.now(UTC))
        stopped_readiness = client.get("/ready")
        assert stopped_readiness.status_code == 503
        assert stopped_readiness.json()["worker"]["status"] == "stopped"

        inventory_before_delete = runtime.artifact_store.inventory_for_video(video_id)
        assert len(inventory_before_delete.artifacts) > 1
        delete_page = client.get(f"/videos/{video_id}/delete")
        assert delete_page.status_code == 200
        confirmed = client.post(
            f"/videos/{video_id}/confirm-delete",
            data={"confirm_filename": source.name},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303
        assert confirmed.headers["location"] == "/?locale=en"

    assert videos.get(video_id) is None
    assert runs.list_for_video(video_id) == []
    assert jobs.list_for_video(video_id) == []
    assert attempts.list_for_run(first_run.id) == []
    assert corrections.list_for_attempt(manual_attempt.id) == []
    assert artifacts.list_for_video(video_id) == []
    deleted_inventory = runtime.artifact_store.inventory_for_video(video_id)
    assert deleted_inventory.artifacts == ()
    assert deleted_inventory.total_bytes == 0


def _run_worker(runtime: LocalRuntime, data_dir: Path, worker_id: str) -> None:
    """Consume exactly one queued job through the real production handler."""

    handler = create_production_handler(database=runtime.database, data_dir=data_dir)
    WorkerProcess(runtime.worker_queue, handler, worker_id=worker_id).run(once=True)


def _settings(tmp_path: Path) -> Settings:
    """Return an isolated local configuration for one HTTP workflow."""

    data_dir = tmp_path / "data"
    database = data_dir / "database" / "shotsight2.db"
    return Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{database}",
        tracking_backend="opencv-cpu",
        worker_readiness_stale_seconds=30.0,
    )


def _generated_no_shot_video(destination: Path) -> Path:
    """Create stable media that exercises decoding and rendering without a shot."""

    completed = subprocess.run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=darkgreen:s=160x90:r=10:d=2.4,drawbox=x=8:y=8:w=144:h=74:color=white:t=2",
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
