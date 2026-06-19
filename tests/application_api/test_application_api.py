"""Integration tests for all Application API routes.

Uses FastAPI TestClient with dependency_overrides to isolate HTTP-layer logic
from service implementations. Covers success paths, validation errors, domain
error translation, and security constraints.

Test IDs follow API-001 through API-XXX.
"""

from __future__ import annotations

import io
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import BinaryIO
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shotsight2.api import register_routes
from shotsight2.api.deps import (
    get_analysis_job_service,
    get_artifact_store,
    get_calibration_service,
    get_deletion_service,
    get_review_service,
    get_tracking_service,
    get_video_ingestion_service,
    get_video_library_service,
)
from shotsight2.domain.artifacts import ArtifactId, ArtifactKind, ArtifactMetadata
from shotsight2.domain.persistence import (
    AnalysisJob,
    AnalysisRun,
    AnalysisStage,
    Calibration,
    JobStatus,
    RunStatus,
    ShotOutcome,
    Video,
    VideoStatus,
)
from shotsight2.domain.review import ReviewQueueItem, ReviewStatus
from shotsight2.ports.artifacts import InvalidArtifactIdError, UnknownArtifactError
from shotsight2.services.analysis_jobs import (
    ActiveAnalysisJobError,
    AnalysisJobSnapshot,
    VideoNotReadyError,
)
from shotsight2.services.deletion import ActiveVideoAnalysisError
from shotsight2.services.video_ingestion import (
    UploadVideoCommand,
    UploadVideoResult,
    VideoIngestionError,
    VideoIngestionErrorCode,
)
from shotsight2.services.video_library import (
    AnalysisProjectionState,
    AnalysisStatusSummary,
    ArtifactAvailabilitySummary,
    LibraryState,
    LibraryStorageSummary,
    PlayerSummary,
    ReviewSummary,
    ShootingSummary,
    ShotTypeSummary,
    VideoCard,
    VideoDetail,
    VideoLibrary,
    VideoStorageSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_app() -> FastAPI:
    app = FastAPI()
    register_routes(app)
    return app


def _video(video_id: str = "v1") -> Video:
    return Video(
        id=video_id,
        filename="game.mp4",
        original_artifact_id="orig-1",
        size_bytes=1024,
        duration_seconds=90.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        container="mp4",
        created_at=_NOW,
        status=VideoStatus.READY,
    )


def _run(run_id: str = "run-1", video_id: str = "v1") -> AnalysisRun:
    return AnalysisRun(
        id=run_id,
        video_id=video_id,
        status=RunStatus.COMPLETED,
        backend_name="opencv-cpu",
        backend_version="0.1.0",
        configuration={},
        progress=1.0,
        stage=AnalysisStage.FINALIZING,
        started_at=_NOW,
    )


def _job(job_id: str = "job-1", video_id: str = "v1", run_id: str = "run-1") -> AnalysisJob:
    return AnalysisJob(
        id=job_id,
        video_id=video_id,
        run_id=run_id,
        status=JobStatus.QUEUED,
        stage=AnalysisStage.VALIDATING,
        progress=0.0,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _snapshot(job_id: str = "job-1", video_id: str = "v1") -> AnalysisJobSnapshot:
    return AnalysisJobSnapshot(
        job=_job(job_id, video_id),
        run=_run(video_id=video_id),
    )


def _shooting_summary() -> ShootingSummary:
    two = ShotTypeSummary("TWO_POINT", 3, 2, 1, 0, 0.67)
    three = ShotTypeSummary("THREE_POINT", 1, 0, 1, 0, 0.0)
    review = ReviewSummary(reviewed=3, unreviewed=1, review_required=0, low_confidence=0, corrected=0, manual=0)
    return ShootingSummary(
        attempts=4,
        makes=2,
        misses=2,
        uncertain=0,
        shooting_percentage=0.5,
        review=review,
        two_point=two,
        three_point=three,
        shot_types=(two, three),
        players=(),
    )


def _artifact_availability() -> ArtifactAvailabilitySummary:
    return ArtifactAvailabilitySummary(
        total_count=0,
        total_size_bytes=0,
        kinds=(),
        references=(),
    )


def _analysis_status(state: AnalysisProjectionState = AnalysisProjectionState.NEVER_ANALYZED) -> AnalysisStatusSummary:
    return AnalysisStatusSummary(
        state=state,
        progress=0.0,
        stage=None,
        latest_run=None,
        published_run=None,
        active_job=None,
        failure=None,
    )


def _video_card(video_id: str = "v1") -> VideoCard:
    return VideoCard(
        video_id=video_id,
        filename="game.mp4",
        status=VideoStatus.READY,
        created_at=_NOW,
        activity_at=_NOW,
        duration_seconds=90.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        container="mp4",
        analysis=_analysis_status(),
        statistics=None,
        artifacts=_artifact_availability(),
        storage=VideoStorageSummary(0, 0, 0),
    )


def _video_detail(video_id: str = "v1") -> VideoDetail:
    return VideoDetail(
        card=_video_card(video_id),
        runs=(),
        jobs=(),
        players=(),
        artifacts=(),
    )


def _library(video_id: str = "v1") -> VideoLibrary:
    return VideoLibrary(
        state=LibraryState.POPULATED,
        videos=(_video_card(video_id),),
        storage=LibraryStorageSummary(1, 0, 0, 0),
    )


def _calibration() -> Calibration:
    return Calibration(
        id="cal-1",
        segment_id="seg-1",
        source="MANUAL",
        rim_geometry={},
        court_points={},
        confidence=1.0,
        indicative_only=False,
        created_at=_NOW,
    )


def _review_item(attempt_id: str = "att-1") -> ReviewQueueItem:
    return ReviewQueueItem(
        attempt_id=attempt_id,
        release_seconds=5.0,
        outcome=ShotOutcome.MADE,
        shot_type="TWO_POINT",
        confidence=0.9,
        review_status=ReviewStatus.UNREVIEWED,
        removed=False,
        is_uncertain=False,
        is_low_confidence=False,
        shooter_track_id=None,
        location_available=False,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    return _make_app()


@pytest.fixture()
def library_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_video_library_service] = lambda: svc
    return svc


@pytest.fixture()
def ingestion_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_video_ingestion_service] = lambda: svc
    return svc


@pytest.fixture()
def job_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_analysis_job_service] = lambda: svc
    return svc


@pytest.fixture()
def deletion_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_deletion_service] = lambda: svc
    return svc


@pytest.fixture()
def calibration_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_calibration_service] = lambda: svc
    return svc


@pytest.fixture()
def review_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_review_service] = lambda: svc
    return svc


@pytest.fixture()
def tracking_svc(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_tracking_service] = lambda: svc
    return svc


@pytest.fixture()
def artifact_store(app: FastAPI) -> MagicMock:
    svc = MagicMock()
    app.dependency_overrides[get_artifact_store] = lambda: svc
    return svc


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# API-001: Error handler registration
# ---------------------------------------------------------------------------


class TestErrorHandlers:
    """API-001: Domain errors translate to correct HTTP status codes."""

    def test_video_not_ready_returns_409(self, app: FastAPI, job_svc: MagicMock) -> None:
        job_svc.request_analysis.side_effect = VideoNotReadyError("not ready")
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/videos/v1/analysis",
            json={"backend_name": "cpu", "backend_version": "1.0"},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "VIDEO_NOT_READY"

    def test_active_job_error_returns_409(self, app: FastAPI, job_svc: MagicMock) -> None:
        job_svc.request_analysis.side_effect = ActiveAnalysisJobError("already running")
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/videos/v1/analysis",
            json={"backend_name": "cpu", "backend_version": "1.0"},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "ACTIVE_JOB_CONFLICT"

    def test_job_not_found_returns_404(self, app: FastAPI, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = None
        resp = TestClient(app, raise_server_exceptions=False).get("/jobs/missing-job")
        assert resp.status_code == 404

    def test_active_video_analysis_during_deletion_returns_409(self, app: FastAPI, deletion_svc: MagicMock) -> None:
        deletion_svc.delete_video.side_effect = ActiveVideoAnalysisError("v1", ("job-1",))
        resp = TestClient(app, raise_server_exceptions=False).delete("/videos/v1")
        assert resp.status_code == 409
        assert resp.json()["code"] == "ACTIVE_JOB_CONFLICT"


# ---------------------------------------------------------------------------
# API-002: Videos — list
# ---------------------------------------------------------------------------


class TestListVideos:
    """API-002: GET /videos returns library projection."""

    def test_returns_200_with_library(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = _library()
        resp = client.get("/videos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "POPULATED"
        assert len(data["videos"]) == 1
        assert data["videos"][0]["video_id"] == "v1"

    def test_empty_library(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/videos")
        assert resp.status_code == 200
        assert resp.json()["state"] == "EMPTY"


# ---------------------------------------------------------------------------
# API-003: Videos — get detail
# ---------------------------------------------------------------------------


class TestGetVideo:
    """API-003: GET /videos/{video_id} returns detail or 404."""

    def test_returns_200_with_detail(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert resp.json()["card"]["video_id"] == "v1"

    def test_returns_404_when_not_found(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = None
        resp = client.get("/videos/missing")
        assert resp.status_code == 404

    def test_blank_video_id_returns_422(self, client: TestClient, library_svc: MagicMock) -> None:
        resp = client.get("/videos/   ")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-004: Videos — upload
# ---------------------------------------------------------------------------


class TestUploadVideo:
    """API-004: POST /videos ingests uploaded file."""

    def test_returns_201_on_success(self, client: TestClient, ingestion_svc: MagicMock) -> None:
        result = UploadVideoResult(
            video=_video(),
            metadata=MagicMock(),
            bytes_written=1024,
        )
        ingestion_svc.ingest.return_value = result
        resp = client.post(
            "/videos",
            files={"file": ("game.mp4", b"fake-video-bytes", "video/mp4")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["video_id"] == "v1"
        assert data["bytes_written"] == 1024
        command = ingestion_svc.ingest.call_args.args[0]
        assert isinstance(command, UploadVideoCommand)
        assert command.chunks is None
        assert command.stream is not None

    def test_returns_422_on_ingestion_error(self, client: TestClient, ingestion_svc: MagicMock) -> None:
        ingestion_svc.ingest.side_effect = VideoIngestionError(
            VideoIngestionErrorCode.SIZE_LIMIT_EXCEEDED, "File exceeds limit"
        )
        resp = client.post(
            "/videos",
            files={"file": ("game.mp4", b"fake-video-bytes", "video/mp4")},
        )
        assert resp.status_code == 422
        assert "size_limit_exceeded" in resp.json()["detail"]["code"]


# ---------------------------------------------------------------------------
# API-005: Videos — delete
# ---------------------------------------------------------------------------


class TestDeleteVideo:
    """API-005: DELETE /videos/{video_id} removes video."""

    def test_returns_204_on_success(self, client: TestClient, deletion_svc: MagicMock) -> None:
        resp = client.delete("/videos/v1")
        assert resp.status_code == 204
        deletion_svc.delete_video.assert_called_once_with("v1")

    def test_blank_id_returns_422(self, client: TestClient, deletion_svc: MagicMock) -> None:
        resp = client.delete("/videos/   ")
        assert resp.status_code == 422
        deletion_svc.delete_video.assert_not_called()


# ---------------------------------------------------------------------------
# API-006: Analysis — start
# ---------------------------------------------------------------------------


class TestStartAnalysis:
    """API-006: POST /videos/{video_id}/analysis starts an analysis job."""

    def test_returns_202_on_success(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.request_analysis.return_value = _snapshot()
        resp = client.post(
            "/videos/v1/analysis",
            json={"backend_name": "opencv-cpu", "backend_version": "0.1.0"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["job"]["id"] == "job-1"

    def test_blank_backend_name_returns_422(self, client: TestClient, job_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/analysis",
            json={"backend_name": "", "backend_version": "0.1.0"},
        )
        assert resp.status_code == 422
        job_svc.request_analysis.assert_not_called()

    def test_blank_backend_version_returns_422(self, client: TestClient, job_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/analysis",
            json={"backend_name": "opencv-cpu", "backend_version": "   "},
        )
        assert resp.status_code == 422
        job_svc.request_analysis.assert_not_called()


# ---------------------------------------------------------------------------
# API-007: Analysis — get status
# ---------------------------------------------------------------------------


class TestGetAnalysisStatus:
    """API-007: GET /videos/{video_id}/analysis returns active job or IDLE."""

    def test_returns_active_job_when_video_matches(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = _snapshot(video_id="v1")
        resp = client.get("/videos/v1/analysis")
        assert resp.status_code == 200
        assert resp.json()["job"]["video_id"] == "v1"

    def test_returns_idle_when_no_active_job(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = None
        resp = client.get("/videos/v1/analysis")
        assert resp.status_code == 200
        assert resp.json()["state"] == "IDLE"
        assert resp.json()["video_id"] == "v1"

    def test_returns_idle_when_active_job_for_different_video(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = _snapshot(video_id="other")
        resp = client.get("/videos/v1/analysis")
        assert resp.status_code == 200
        assert resp.json()["state"] == "IDLE"


# ---------------------------------------------------------------------------
# API-008: Jobs — get by ID
# ---------------------------------------------------------------------------


class TestGetJob:
    """API-008: GET /jobs/{job_id} returns active job or 404."""

    def test_returns_job_when_active_and_id_matches(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = _snapshot("job-1")
        resp = client.get("/jobs/job-1")
        assert resp.status_code == 200
        assert resp.json()["job"]["id"] == "job-1"

    def test_returns_404_when_no_active_job(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = None
        resp = client.get("/jobs/job-1")
        assert resp.status_code == 404

    def test_returns_404_when_active_job_id_does_not_match(self, client: TestClient, job_svc: MagicMock) -> None:
        job_svc.current_job.return_value = _snapshot("other-job")
        resp = client.get("/jobs/job-1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-009: Segments — list
# ---------------------------------------------------------------------------


class TestListSegments:
    """API-009: GET /videos/{video_id}/segments returns calibration models."""

    def test_returns_list_of_models(self, client: TestClient, calibration_svc: MagicMock) -> None:
        from shotsight2.domain.calibration import (
            CalibrationAssessment,
            CalibrationValidity,
        )
        from shotsight2.services.calibration import PresentationCalibrationModel

        assessment = CalibrationAssessment(
            validity=CalibrationValidity.INVALID,
            confidence=0.0,
            reasons=(),
        )
        model = PresentationCalibrationModel(
            segment_id="seg-1",
            analysis_run_id="run-1",
            start_seconds=0.0,
            end_seconds=30.0,
            representative_artifact_id=None,
            active_calibration_id=None,
            source=None,
            rim=None,
            court_points=(),
            assessment=assessment,
            indicative_only=False,
        )
        calibration_svc.presentation_models_for_run.return_value = (model,)
        resp = client.get("/videos/v1/segments?run_id=run-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["segment_id"] == "seg-1"

    def test_returns_empty_list(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.presentation_models_for_run.return_value = ()
        resp = client.get("/videos/v1/segments?run_id=run-1")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# API-010: Segments — calibration correction
# ---------------------------------------------------------------------------


class TestCorrectCalibration:
    """API-010: PATCH /videos/{video_id}/segments/{segment_id}/calibration."""

    def test_returns_updated_calibration(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.correct_segment.return_value = _calibration()
        resp = client.patch(
            "/videos/v1/segments/seg-1/calibration",
            json={"segment_id": "seg-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "cal-1"

    def test_segment_id_mismatch_returns_422(self, client: TestClient, calibration_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/segments/seg-1/calibration",
            json={"segment_id": "seg-2"},
        )
        assert resp.status_code == 422
        calibration_svc.correct_segment.assert_not_called()

    def test_invalid_court_reference_point_returns_422(self, client: TestClient, calibration_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/segments/seg-1/calibration",
            json={
                "segment_id": "seg-1",
                "court_points": {"UNKNOWN_POINT": {"x": 10, "y": 20}},
            },
        )
        assert resp.status_code == 422
        calibration_svc.correct_segment.assert_not_called()


# ---------------------------------------------------------------------------
# API-011: Players — list and rename
# ---------------------------------------------------------------------------


class TestPlayers:
    """API-011: Player list and rename routes."""

    def test_list_players_returns_players(self, client: TestClient, library_svc: MagicMock) -> None:
        player = PlayerSummary(
            player_track_id="pt-1",
            display_name="Player 1",
            attempts=3,
            makes=2,
            misses=1,
            uncertain=0,
            shooting_percentage=0.67,
        )
        detail = _video_detail()
        # Build a detail with a player
        from dataclasses import replace

        card_with_stats = replace(detail.card, statistics=replace(_shooting_summary(), players=(player,)))
        detail_with_player = replace(detail, card=card_with_stats, players=(player,))
        library_svc.get_video_detail.return_value = detail_with_player
        resp = client.get("/videos/v1/players")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["player_track_id"] == "pt-1"

    def test_list_players_404_when_video_absent(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = None
        resp = client.get("/videos/missing/players")
        assert resp.status_code == 404

    def test_rename_player_returns_updated(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/players/pt-1",
            json={"display_name": "Alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_track_id"] == "pt-1"
        assert data["display_name"] == "Alice"
        review_svc.rename_player.assert_called_once_with("pt-1", "Alice")

    def test_rename_player_blank_name_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/players/pt-1",
            json={"display_name": ""},
        )
        assert resp.status_code == 422
        review_svc.rename_player.assert_not_called()


# ---------------------------------------------------------------------------
# API-012: Attempts — list, create, update, delete
# ---------------------------------------------------------------------------


class TestAttempts:
    """API-012: Shot attempt CRUD routes."""

    def test_list_returns_queue(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = (_review_item(),)
        resp = client.get("/videos/v1/attempts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["attempt_id"] == "att-1"

    def test_create_attempt_returns_201(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.create_manual_attempt.return_value = _shooting_summary()
        resp = client.post(
            "/videos/v1/attempts",
            json={
                "run_id": "run-1",
                "release_seconds": 5.0,
                "shot_type": "TWO_POINT",
                "outcome": "MADE",
            },
        )
        assert resp.status_code == 201
        review_svc.create_manual_attempt.assert_called_once()

    def test_create_attempt_invalid_outcome_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/attempts",
            json={
                "run_id": "run-1",
                "release_seconds": 5.0,
                "shot_type": "TWO_POINT",
                "outcome": "INVALID_OUTCOME",
            },
        )
        assert resp.status_code == 422
        review_svc.create_manual_attempt.assert_not_called()

    def test_create_attempt_blank_shot_type_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/attempts",
            json={
                "run_id": "run-1",
                "release_seconds": 5.0,
                "shot_type": "",
                "outcome": "MADE",
            },
        )
        assert resp.status_code == 422
        review_svc.create_manual_attempt.assert_not_called()

    def test_update_attempt_outcome(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.override_outcome.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "outcome", "value": "MISSED"},
        )
        assert resp.status_code == 200
        review_svc.override_outcome.assert_called_once()

    def test_update_attempt_invalid_outcome_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "outcome", "value": "BASKET"},
        )
        assert resp.status_code == 422

    def test_update_attempt_shooter(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.override_shooter.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "shooter_track_id", "value": "pt-1"},
        )
        assert resp.status_code == 200
        review_svc.override_shooter.assert_called_once()

    def test_update_attempt_shot_type(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.override_shot_type.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "shot_type", "value": "THREE_POINT"},
        )
        assert resp.status_code == 200
        review_svc.override_shot_type.assert_called_once()

    def test_update_attempt_blank_shot_type_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "shot_type", "value": ""},
        )
        assert resp.status_code == 422

    def test_update_attempt_location(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.override_location.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={
                "field": "location",
                "value": {
                    "normalized_x": 0.5,
                    "normalized_y": 0.3,
                    "region": "paint",
                },
            },
        )
        assert resp.status_code == 200

    def test_update_attempt_remove(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.remove_attempt.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "removed", "value": True},
        )
        assert resp.status_code == 200
        review_svc.remove_attempt.assert_called_once()

    def test_update_attempt_restore(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.restore_attempt.return_value = _shooting_summary()
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "removed", "value": False},
        )
        assert resp.status_code == 200
        review_svc.restore_attempt.assert_called_once()

    def test_update_attempt_unknown_field_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.patch(
            "/videos/v1/attempts/att-1",
            json={"field": "not_a_real_field", "value": "x"},
        )
        assert resp.status_code == 422

    def test_delete_attempt_returns_204(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.remove_attempt.return_value = _shooting_summary()
        resp = client.delete("/videos/v1/attempts/att-1")
        assert resp.status_code == 204
        review_svc.remove_attempt.assert_called_once()


# ---------------------------------------------------------------------------
# API-013: Tracking prompts
# ---------------------------------------------------------------------------


class TestTrackingPrompts:
    """API-013: POST /videos/{video_id}/tracking/prompts."""

    def test_submits_point_prompt(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "basketball",
                "kind": "point",
                "point": {"x": 100.0, "y": 200.0},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["accepted"] is True
        tracking_svc.save_user_prompt.assert_called_once()

    def test_submits_box_prompt(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "basketball",
                "kind": "box",
                "box": {"x": 10, "y": 20, "width": 50, "height": 60},
            },
        )
        assert resp.status_code == 201

    def test_unknown_kind_returns_422(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "basketball",
                "kind": "polygon",
            },
        )
        assert resp.status_code == 422
        tracking_svc.save_user_prompt.assert_not_called()

    def test_unknown_object_class_returns_422(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "UFO",
                "kind": "point",
                "point": {"x": 10, "y": 10},
            },
        )
        assert resp.status_code == 422

    def test_point_prompt_without_point_geometry_returns_422(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "basketball",
                "kind": "point",
            },
        )
        assert resp.status_code == 422

    def test_box_prompt_without_box_geometry_returns_422(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/prompts",
            json={
                "segment_id": "seg-1",
                "timestamp_seconds": 3.0,
                "object_class": "basketball",
                "kind": "box",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-014: Artifact streaming
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal ArtifactStore fake for artifact streaming tests."""

    def __init__(self, content: bytes = b"hello world", media_type: str = "video/mp4") -> None:
        self._content = content
        self._media_type = media_type

    def metadata(self, artifact_id: ArtifactId) -> ArtifactMetadata:
        if "missing" in str(artifact_id):
            raise UnknownArtifactError(artifact_id)
        if "invalid" in str(artifact_id):
            raise InvalidArtifactIdError(artifact_id)
        return ArtifactMetadata(
            artifact_id=artifact_id,
            kind=ArtifactKind.ORIGINAL,
            logical_path="video/v1/game.mp4",
            size_bytes=len(self._content),
            media_type=self._media_type,
        )

    @contextmanager
    def open_read(self, artifact_id: ArtifactId) -> Generator[BinaryIO, None, None]:
        yield io.BytesIO(self._content)


class TestArtifactStreaming:
    """API-014: GET /artifacts/{artifact_id:path} streams with range support."""

    @pytest.fixture()
    def fake_store(self) -> _FakeStore:
        return _FakeStore(content=b"A" * 100)

    @pytest.fixture()
    def stream_client(self, app: FastAPI, fake_store: _FakeStore) -> TestClient:
        app.dependency_overrides[get_artifact_store] = lambda: fake_store
        return TestClient(app, raise_server_exceptions=False)

    def test_full_stream_returns_200(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/v1/game.mp4")
        assert resp.status_code == 200
        assert resp.content == b"A" * 100
        assert resp.headers["content-length"] == "100"
        assert resp.headers["accept-ranges"] == "bytes"

    def test_ranged_request_returns_206(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/v1/game.mp4", headers={"Range": "bytes=0-9"})
        assert resp.status_code == 206
        assert resp.content == b"A" * 10
        assert resp.headers["content-range"] == "bytes 0-9/100"

    def test_open_ended_range_request(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/v1/game.mp4", headers={"Range": "bytes=90-"})
        assert resp.status_code == 206
        assert resp.content == b"A" * 10
        assert resp.headers["content-range"] == "bytes 90-99/100"

    def test_unsatisfiable_range_returns_416(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/v1/game.mp4", headers={"Range": "bytes=200-300"})
        assert resp.status_code == 416

    def test_missing_artifact_returns_404(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/missing/game.mp4")
        assert resp.status_code == 404

    def test_invalid_artifact_id_returns_422(self, stream_client: TestClient) -> None:
        resp = stream_client.get("/artifacts/video/invalid/game.mp4")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-015: Preferences
# ---------------------------------------------------------------------------


class TestPreferences:
    """API-015: Language preference get and update."""

    @pytest.fixture(autouse=True)
    def reset_locale(self) -> Generator[None, None, None]:
        """Reset module-level locale state between tests."""
        from shotsight2.api.routers import preferences

        original = preferences._current_locale
        yield
        preferences._current_locale = original

    def test_get_default_locale(self, client: TestClient) -> None:
        from shotsight2.api.routers import preferences

        preferences._current_locale = "en"
        resp = client.get("/preferences/language")
        assert resp.status_code == 200
        assert resp.json()["locale"] == "en"

    def test_update_to_chinese(self, client: TestClient) -> None:
        resp = client.put("/preferences/language", json={"locale": "zh"})
        assert resp.status_code == 200
        assert resp.json()["locale"] == "zh"

    def test_update_to_english(self, client: TestClient) -> None:
        resp = client.put("/preferences/language", json={"locale": "en"})
        assert resp.status_code == 200
        assert resp.json()["locale"] == "en"

    def test_invalid_locale_returns_422(self, client: TestClient) -> None:
        resp = client.put("/preferences/language", json={"locale": "fr"})
        assert resp.status_code == 422

    def test_get_reflects_update(self, client: TestClient) -> None:
        client.put("/preferences/language", json={"locale": "zh"})
        resp = client.get("/preferences/language")
        assert resp.json()["locale"] == "zh"


# ---------------------------------------------------------------------------
# API-016: register_routes idempotency / app structure
# ---------------------------------------------------------------------------


class TestAppStructure:
    """API-016: register_routes wires all expected routes."""

    def test_all_expected_routes_present(self) -> None:
        app = _make_app()
        # Collect all route paths from the OpenAPI schema
        openapi = app.openapi()
        paths = set(openapi["paths"].keys())
        expected = {
            "/videos",
            "/videos/{video_id}",
            "/videos/{video_id}/analysis",
            "/jobs/{job_id}",
            "/videos/{video_id}/segments",
            "/videos/{video_id}/segments/{segment_id}/calibration",
            "/videos/{video_id}/players",
            "/videos/{video_id}/players/{player_track_id}",
            "/videos/{video_id}/attempts",
            "/videos/{video_id}/attempts/{attempt_id}",
            "/videos/{video_id}/tracking/prompts",
            "/artifacts/{artifact_id}",
            "/preferences/language",
        }
        for path in expected:
            assert path in paths, f"Missing route: {path}"
