"""Tests for the Presentation module.

Verifies that pages render using API-provided data only (no direct DB/FS access),
cover both English and Chinese locales, and exercise all major workflows.

Test IDs follow PRE-001 through PRE-015.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shotsight2.api.deps import (
    get_analysis_job_service,
    get_calibration_service,
    get_deletion_service,
    get_review_service,
    get_tracking_service,
    get_video_ingestion_service,
    get_video_library_service,
)
from shotsight2.domain.calibration import CalibrationAssessment, CalibrationValidity
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
from shotsight2.presentation import register_presentation
from shotsight2.presentation.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, get_catalog, t
from shotsight2.services.analysis_jobs import AnalysisJobSnapshot, VideoNotReadyError
from shotsight2.services.calibration import PresentationCalibrationModel
from shotsight2.services.video_ingestion import (
    UploadVideoResult,
    VideoIngestionError,
    VideoIngestionErrorCode,
)
from shotsight2.services.video_library import (
    AnalysisProjectionState,
    AnalysisStatusSummary,
    ArtifactAvailabilitySummary,
    ArtifactReference,
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
# Test data helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


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


def _job(job_id: str = "job-1", video_id: str = "v1") -> AnalysisJob:
    return AnalysisJob(
        id=job_id,
        video_id=video_id,
        run_id="run-1",
        status=JobStatus.QUEUED,
        stage=AnalysisStage.VALIDATING,
        progress=0.0,
        created_at=_NOW,
        updated_at=_NOW,
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


def _snapshot(job_id: str = "job-1", video_id: str = "v1") -> AnalysisJobSnapshot:
    return AnalysisJobSnapshot(job=_job(job_id, video_id), run=_run(video_id=video_id))


def _analysis_status(
    state: AnalysisProjectionState = AnalysisProjectionState.NEVER_ANALYZED,
) -> AnalysisStatusSummary:
    return AnalysisStatusSummary(
        state=state,
        progress=0.0,
        stage=None,
        latest_run=None,
        published_run=None,
        active_job=None,
        failure=None,
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


def _video_card(
    video_id: str = "v1",
    state: AnalysisProjectionState = AnalysisProjectionState.NEVER_ANALYZED,
) -> VideoCard:
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
        analysis=_analysis_status(state),
        statistics=None,
        artifacts=ArtifactAvailabilitySummary(total_count=0, total_size_bytes=0, kinds=(), references=()),
        storage=VideoStorageSummary(0, 0, 0),
    )


def _video_detail(video_id: str = "v1", with_stats: bool = False) -> VideoDetail:
    card = _video_card(video_id, AnalysisProjectionState.COMPLETED)
    if with_stats:
        card = replace(card, statistics=_shooting_summary())
    return VideoDetail(card=card, runs=(), jobs=(), players=(), artifacts=())


def _library(video_id: str = "v1") -> VideoLibrary:
    return VideoLibrary(
        state=LibraryState.POPULATED,
        videos=(_video_card(video_id),),
        storage=LibraryStorageSummary(1, 0, 0, 0),
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


def _calibration_model() -> PresentationCalibrationModel:
    assessment = CalibrationAssessment(validity=CalibrationValidity.INVALID, confidence=0.0, reasons=())
    return PresentationCalibrationModel(
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


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    register_presentation(app)
    return app


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
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# PRE-001: Package structure
# ---------------------------------------------------------------------------


class TestPackageStructure:
    """PRE-001: Presentation package structure and entrypoint."""

    def test_register_presentation_is_callable(self) -> None:
        app = FastAPI()
        register_presentation(app)

    def test_all_expected_routes_present(self) -> None:
        app = _make_app()
        openapi = app.openapi()
        paths = set(openapi["paths"].keys())
        expected = {
            "/",
            "/upload",
            "/videos/{video_id}",
            "/videos/{video_id}/calibration",
            "/videos/{video_id}/players",
            "/videos/{video_id}/attempts",
            "/videos/{video_id}/statistics",
            "/videos/{video_id}/tracking-repair",
            "/videos/{video_id}/delete",
            "/preferences/language-ui",
        }
        for path in expected:
            assert path in paths, f"Missing presentation route: {path}"


# ---------------------------------------------------------------------------
# PRE-002/PRE-003: Shell and locale
# ---------------------------------------------------------------------------


class TestShellAndLocale:
    """PRE-002/PRE-003: Application shell renders in both locales."""

    def test_library_renders_english(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/?locale=en")
        assert resp.status_code == 200
        assert "ShotSight" in resp.text
        assert t("library.title", "en") in resp.text
        assert t("nav.upload", "en") in resp.text

    def test_library_renders_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/?locale=zh")
        assert resp.status_code == 200
        assert t("library.title", "zh") in resp.text
        assert t("nav.upload", "zh") in resp.text

    def test_unsupported_locale_falls_back_to_english(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/?locale=fr")
        assert resp.status_code == 200
        assert t("library.title", "en") in resp.text

    def test_locale_switch_redirects(self, client: TestClient) -> None:
        resp = client.get("/preferences/language-ui?locale=zh", follow_redirects=False)
        assert resp.status_code == 303
        assert "locale=zh" in resp.headers["location"]

    def test_locale_switch_invalid_falls_back(self, client: TestClient) -> None:
        resp = client.get("/preferences/language-ui?locale=de", follow_redirects=False)
        assert resp.status_code == 303
        assert "locale=en" in resp.headers["location"]


# ---------------------------------------------------------------------------
# PRE-003: Translation catalog
# ---------------------------------------------------------------------------


class TestTranslationCatalog:
    """PRE-003: Translation catalog completeness."""

    def test_all_english_keys_present_in_chinese(self) -> None:
        en = get_catalog("en")
        zh = get_catalog("zh")
        missing = set(en) - set(zh)
        assert not missing, f"Chinese catalog missing keys: {missing}"

    def test_t_falls_back_to_english_for_unknown_locale(self) -> None:
        result = t("nav.library", "xx")
        assert result == t("nav.library", "en")

    def test_t_interpolates_kwargs(self) -> None:
        result = t("library.video_count", "en", n=5)
        assert "5" in result

    def test_supported_locales(self) -> None:
        assert "en" in SUPPORTED_LOCALES
        assert "zh" in SUPPORTED_LOCALES
        assert DEFAULT_LOCALE == "en"


# ---------------------------------------------------------------------------
# PRE-004: Video library page
# ---------------------------------------------------------------------------


class TestLibraryPage:
    """PRE-004: Video library root screen."""

    def test_renders_populated_library(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = _library()
        resp = client.get("/")
        assert resp.status_code == 200
        assert "game.mp4" in resp.text

    def test_renders_empty_state(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert t("library.empty", "en") in resp.text

    def test_shows_statistics_when_available(self, client: TestClient, library_svc: MagicMock) -> None:
        card = replace(_video_card(), statistics=_shooting_summary())
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.POPULATED,
            videos=(card,),
            storage=LibraryStorageSummary(1, 0, 0, 0),
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert "4 att" in resp.text

    def test_library_page_in_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = _library()
        resp = client.get("/?locale=zh")
        assert resp.status_code == 200
        assert t("library.title", "zh") in resp.text


# ---------------------------------------------------------------------------
# PRE-005: Upload form
# ---------------------------------------------------------------------------


class TestUploadPage:
    """PRE-005: Upload form and validation."""

    def test_get_upload_page(self, client: TestClient) -> None:
        resp = client.get("/upload")
        assert resp.status_code == 200
        assert t("upload.title", "en") in resp.text
        assert t("upload.hint", "en") in resp.text

    def test_upload_page_chinese(self, client: TestClient) -> None:
        resp = client.get("/upload?locale=zh")
        assert resp.status_code == 200
        assert t("upload.title", "zh") in resp.text

    def test_successful_upload_redirects(self, client: TestClient, ingestion_svc: MagicMock) -> None:
        ingestion_svc.ingest.return_value = UploadVideoResult(
            video=_video(),
            metadata=MagicMock(),
            bytes_written=1024,
        )
        resp = client.post(
            "/upload",
            files={"file": ("game.mp4", b"fake", "video/mp4")},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/videos/v1" in resp.headers["location"]

    def test_ingestion_error_shows_form_error(self, client: TestClient, ingestion_svc: MagicMock) -> None:
        ingestion_svc.ingest.side_effect = VideoIngestionError(VideoIngestionErrorCode.SIZE_LIMIT_EXCEEDED, "Too large")
        resp = client.post(
            "/upload",
            files={"file": ("game.mp4", b"fake", "video/mp4")},
        )
        assert resp.status_code == 422
        assert "Too large" in resp.text


# ---------------------------------------------------------------------------
# PRE-006: Video detail page
# ---------------------------------------------------------------------------


class TestVideoDetailPage:
    """PRE-006: Video detail with metadata, actions, and artifact links."""

    def test_renders_detail(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert "game.mp4" in resp.text
        assert t("detail.analyze", "en") in resp.text

    def test_returns_404_for_missing_video(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = None
        resp = client.get("/videos/missing")
        assert resp.status_code == 404

    def test_detail_page_in_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1?locale=zh")
        assert resp.status_code == 200
        assert t("detail.title", "zh") in resp.text

    def test_detail_shows_artifact_links(self, client: TestClient, library_svc: MagicMock) -> None:
        art = ArtifactReference(
            artifact_id="video/v1/game.mp4",
            video_id="v1",
            analysis_run_id=None,
            kind="original",
            version="1",
            size_bytes=1024,
            created_at=_NOW,
        )
        detail = replace(_video_detail(), artifacts=(art,))
        library_svc.get_video_detail.return_value = detail
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert "video/v1/game.mp4" in resp.text

    def test_start_analysis_redirects_on_success(
        self,
        client: TestClient,
        job_svc: MagicMock,
        library_svc: MagicMock,
    ) -> None:
        job_svc.request_analysis.return_value = _snapshot()
        resp = client.post(
            "/videos/v1/analyze",
            data={"backend_name": "opencv-cpu", "backend_version": "0.1.0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_start_analysis_shows_error_on_not_ready(
        self,
        client: TestClient,
        job_svc: MagicMock,
        library_svc: MagicMock,
    ) -> None:
        job_svc.request_analysis.side_effect = VideoNotReadyError("not ready")
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.post(
            "/videos/v1/analyze",
            data={"backend_name": "opencv-cpu", "backend_version": "0.1.0"},
        )
        assert resp.status_code == 409
        assert "not ready" in resp.text


# ---------------------------------------------------------------------------
# PRE-007: Analysis progress
# ---------------------------------------------------------------------------


class TestAnalysisProgress:
    """PRE-007: Progress display with polling for running jobs."""

    def test_running_job_shows_progress_bar(self, client: TestClient, library_svc: MagicMock) -> None:
        card = replace(
            _video_card(state=AnalysisProjectionState.RUNNING),
            analysis=replace(
                _analysis_status(AnalysisProjectionState.RUNNING),
                progress=0.45,
            ),
        )
        detail = replace(_video_detail(), card=card)
        library_svc.get_video_detail.return_value = detail
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert "45%" in resp.text
        assert t("progress.polling", "en") in resp.text

    def test_completed_job_shows_done_message(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert t("progress.done", "en") in resp.text


# ---------------------------------------------------------------------------
# PRE-008: Calibration
# ---------------------------------------------------------------------------


class TestCalibrationPage:
    """PRE-008: Calibration review and correction."""

    def test_renders_calibration_models(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.presentation_models_for_run.return_value = (_calibration_model(),)
        resp = client.get("/videos/v1/calibration?run_id=run-1")
        assert resp.status_code == 200
        assert "seg-1" in resp.text
        assert t("calibration.save", "en") in resp.text

    def test_empty_calibration_list(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.presentation_models_for_run.return_value = ()
        resp = client.get("/videos/v1/calibration?run_id=run-1")
        assert resp.status_code == 200

    def test_calibration_page_chinese(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.presentation_models_for_run.return_value = ()
        resp = client.get("/videos/v1/calibration?run_id=run-1&locale=zh")
        assert resp.status_code == 200
        assert t("calibration.title", "zh") in resp.text

    def test_correction_redirects_on_success(self, client: TestClient, calibration_svc: MagicMock) -> None:
        calibration_svc.correct_segment.return_value = _calibration()
        resp = client.post(
            "/videos/v1/segments/seg-1/calibration",
            data={"segment_id": "seg-1", "run_id": "run-1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        calibration_svc.correct_segment.assert_called_once()


# ---------------------------------------------------------------------------
# PRE-009: Players
# ---------------------------------------------------------------------------


class TestPlayersPage:
    """PRE-009: Player list with rename support."""

    def test_renders_players(self, client: TestClient, library_svc: MagicMock) -> None:
        player = PlayerSummary(
            player_track_id="pt-1",
            display_name="Alice",
            attempts=3,
            makes=2,
            misses=1,
            uncertain=0,
            shooting_percentage=0.67,
        )
        detail = replace(_video_detail(), players=(player,))
        library_svc.get_video_detail.return_value = detail
        resp = client.get("/videos/v1/players")
        assert resp.status_code == 200
        assert "Alice" in resp.text
        assert t("players.rename", "en") in resp.text

    def test_empty_players(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1/players")
        assert resp.status_code == 200
        assert t("players.no_players", "en") in resp.text

    def test_players_page_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1/players?locale=zh")
        assert resp.status_code == 200
        assert t("players.title", "zh") in resp.text

    def test_rename_player_redirects(self, client: TestClient, review_svc: MagicMock, library_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/players/pt-1",
            data={"display_name": "Bob"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        review_svc.rename_player.assert_called_once_with("pt-1", "Bob")

    def test_rename_blank_name_returns_422(
        self, client: TestClient, review_svc: MagicMock, library_svc: MagicMock
    ) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.post(
            "/videos/v1/players/pt-1",
            data={"display_name": ""},
        )
        assert resp.status_code == 422
        review_svc.rename_player.assert_not_called()


# ---------------------------------------------------------------------------
# PRE-010: Attempts review
# ---------------------------------------------------------------------------


class TestAttemptsPage:
    """PRE-010: Attempt review with navigation and editing."""

    def test_renders_attempt_list(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = (_review_item(),)
        resp = client.get("/videos/v1/attempts")
        assert resp.status_code == 200
        assert t("attempts.title", "en") in resp.text
        assert "att-1" in resp.text or "5.00s" in resp.text

    def test_empty_attempts_shows_empty_state(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = ()
        resp = client.get("/videos/v1/attempts")
        assert resp.status_code == 200
        assert t("attempts.no_attempts", "en") in resp.text

    def test_attempts_page_chinese(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = ()
        resp = client.get("/videos/v1/attempts?locale=zh")
        assert resp.status_code == 200
        assert t("attempts.title", "zh") in resp.text

    def test_edit_attempt_page(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = (_review_item("att-1"), _review_item("att-2"))
        resp = client.get("/videos/v1/attempts/att-1")
        assert resp.status_code == 200
        assert t("common.save", "en") in resp.text

    def test_edit_missing_attempt_returns_404(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.build_review_queue.return_value = ()
        resp = client.get("/videos/v1/attempts/missing")
        assert resp.status_code == 404

    def test_update_attempt_redirects(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.override_outcome.return_value = _shooting_summary()
        review_svc.override_shot_type.return_value = _shooting_summary()
        review_svc.override_shooter.return_value = _shooting_summary()
        resp = client.post(
            "/videos/v1/attempts/att-1/update",
            data={"outcome": "MADE", "shot_type": "TWO_POINT", "shooter_track_id": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_remove_attempt_redirects(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.remove_attempt.return_value = _shooting_summary()
        resp = client.post("/videos/v1/attempts/att-1/remove", follow_redirects=False)
        assert resp.status_code == 303
        review_svc.remove_attempt.assert_called_once()

    def test_restore_attempt_redirects(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.restore_attempt.return_value = _shooting_summary()
        resp = client.post("/videos/v1/attempts/att-1/restore", follow_redirects=False)
        assert resp.status_code == 303

    def test_new_attempt_page(self, client: TestClient) -> None:
        resp = client.get("/videos/v1/attempts/new")
        assert resp.status_code == 200
        assert t("attempts.new", "en") in resp.text

    def test_create_attempt_redirects(self, client: TestClient, review_svc: MagicMock) -> None:
        review_svc.create_manual_attempt.return_value = _shooting_summary()
        resp = client.post(
            "/videos/v1/attempts/create",
            data={"run_id": "run-1", "release_seconds": "5.0", "shot_type": "TWO_POINT", "outcome": "MADE"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_create_attempt_invalid_outcome_returns_422(self, client: TestClient, review_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/attempts/create",
            data={"run_id": "run-1", "release_seconds": "5.0", "shot_type": "TWO_POINT", "outcome": "BASKET"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PRE-011: Statistics
# ---------------------------------------------------------------------------


class TestStatisticsPage:
    """PRE-011: Shot stats, artifact links."""

    def test_renders_statistics(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail(with_stats=True)
        resp = client.get("/videos/v1/statistics")
        assert resp.status_code == 200
        assert t("stats.title", "en") in resp.text
        assert "50%" in resp.text

    def test_statistics_page_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail(with_stats=True)
        resp = client.get("/videos/v1/statistics?locale=zh")
        assert resp.status_code == 200
        assert t("stats.title", "zh") in resp.text

    def test_statistics_404_when_video_missing(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = None
        resp = client.get("/videos/missing/statistics")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PRE-012: Tracking repair
# ---------------------------------------------------------------------------


class TestTrackingRepairPage:
    """PRE-012: Tracking-repair prompt controls."""

    def test_renders_form(self, client: TestClient) -> None:
        resp = client.get("/videos/v1/tracking-repair")
        assert resp.status_code == 200
        assert t("tracking.title", "en") in resp.text

    def test_form_chinese(self, client: TestClient) -> None:
        resp = client.get("/videos/v1/tracking-repair?locale=zh")
        assert resp.status_code == 200
        assert t("tracking.title", "zh") in resp.text

    def test_submit_point_prompt_redirects(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/submit",
            data={
                "segment_id": "seg-1",
                "timestamp_seconds": "3.0",
                "kind": "point",
                "point_x": "100",
                "point_y": "200",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        tracking_svc.save_user_prompt.assert_called_once()

    def test_submit_box_prompt_redirects(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/submit",
            data={
                "segment_id": "seg-1",
                "timestamp_seconds": "3.0",
                "kind": "box",
                "box_x": "10",
                "box_y": "20",
                "box_w": "50",
                "box_h": "60",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_missing_geometry_returns_422(self, client: TestClient, tracking_svc: MagicMock) -> None:
        resp = client.post(
            "/videos/v1/tracking/submit",
            data={"segment_id": "seg-1", "timestamp_seconds": "3.0", "kind": "point"},
        )
        assert resp.status_code == 422
        tracking_svc.save_user_prompt.assert_not_called()


# ---------------------------------------------------------------------------
# PRE-013: Deletion
# ---------------------------------------------------------------------------


class TestDeletionPage:
    """PRE-013: Deletion inventory and confirmation dialog."""

    def test_renders_deletion_page(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1/delete")
        assert resp.status_code == 200
        assert t("deletion.warning", "en") in resp.text
        assert "game.mp4" in resp.text

    def test_deletion_page_chinese(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.get("/videos/v1/delete?locale=zh")
        assert resp.status_code == 200
        assert t("deletion.warning", "zh") in resp.text

    def test_deletion_page_404_for_missing_video(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.get_video_detail.return_value = None
        resp = client.get("/videos/missing/delete")
        assert resp.status_code == 404

    def test_confirm_delete_redirects_on_correct_filename(
        self, client: TestClient, library_svc: MagicMock, deletion_svc: MagicMock
    ) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.post(
            "/videos/v1/confirm-delete",
            data={"confirm_filename": "game.mp4"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/")
        deletion_svc.delete_video.assert_called_once_with("v1")

    def test_confirm_delete_rejects_wrong_filename(
        self, client: TestClient, library_svc: MagicMock, deletion_svc: MagicMock
    ) -> None:
        library_svc.get_video_detail.return_value = _video_detail()
        resp = client.post(
            "/videos/v1/confirm-delete",
            data={"confirm_filename": "wrong.mp4"},
        )
        assert resp.status_code == 422
        assert "does not match" in resp.text
        deletion_svc.delete_video.assert_not_called()


# ---------------------------------------------------------------------------
# PRE-014: Accessibility / loading / error states
# ---------------------------------------------------------------------------


class TestAccessibilityAndStates:
    """PRE-014: Responsive, keyboard-accessible, loading, empty, error states."""

    def test_pages_use_semantic_html(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<nav" in resp.text
        assert "<main" in resp.text

    def test_progress_bar_has_aria_attrs(self, client: TestClient, library_svc: MagicMock) -> None:
        card = replace(
            _video_card(state=AnalysisProjectionState.RUNNING),
            analysis=replace(_analysis_status(AnalysisProjectionState.RUNNING), progress=0.3),
        )
        library_svc.get_video_detail.return_value = replace(_video_detail(), card=card)
        resp = client.get("/videos/v1")
        assert resp.status_code == 200
        assert 'role="progressbar"' in resp.text
        assert "aria-valuenow" in resp.text

    def test_upload_form_has_required_label(self, client: TestClient) -> None:
        resp = client.get("/upload")
        assert resp.status_code == 200
        assert 'aria-required="true"' in resp.text

    def test_locale_selector_has_label(self, client: TestClient, library_svc: MagicMock) -> None:
        library_svc.list_videos.return_value = VideoLibrary(
            state=LibraryState.EMPTY, videos=(), storage=LibraryStorageSummary(0, 0, 0, 0)
        )
        resp = client.get("/")
        assert resp.status_code == 200
        assert "visually-hidden" in resp.text
