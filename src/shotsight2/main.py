"""FastAPI entrypoint for the ShotSight 2.0 local web application."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from shotsight2.adapters.backend_probes import (
    BackendProbeConfig,
    BackendRegistry,
    create_default_registry,
)
from shotsight2.adapters.ffmpeg import FFmpegAdapter
from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.mlx_sam3 import MLXSam3ImageBackend
from shotsight2.adapters.opencv import OpenCVTrackingBackend, OpenCVTrackingFrameSource
from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteCalibrationRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDatabase,
    SQLiteDeletionRepository,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteShotAttemptRepository,
    SQLiteTrackingObservationRepository,
    SQLiteTrackingPromptRepository,
    SQLiteVideoRepository,
)
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
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
from shotsight2.api.routers.health import (
    get_artifact_store_optional,
    get_backend_registry,
    get_media_tool,
    get_settings,
    get_system_profile,
)
from shotsight2.config import Settings, settings
from shotsight2.domain.tracking import ModelConfig
from shotsight2.domain.tracking_backends import SystemProfile, TrackingBackendName
from shotsight2.ports.tracking import TrackingBackend
from shotsight2.services import (
    AnalysisJobService,
    CalibrationService,
    StatisticsService,
    VideoDeletionService,
    VideoIngestionLimits,
    VideoIngestionService,
    VideoLibraryService,
)
from shotsight2.services.review import ReviewService
from shotsight2.services.tracking import TrackingOrchestrator


@dataclass(frozen=True, slots=True)
class LocalRuntime:
    """Concrete runtime dependencies owned by one FastAPI app instance."""

    database: SQLiteDatabase
    artifact_store: FileSystemArtifactStore
    media_tool: FFmpegAdapter
    video_library: VideoLibraryService
    video_ingestion: VideoIngestionService
    analysis_jobs: AnalysisJobService
    deletion: VideoDeletionService
    calibration: CalibrationService
    review: ReviewService
    tracking: TrackingOrchestrator


def create_app(
    application_settings: Settings = settings,
    *,
    backend_registry: BackendRegistry | None = None,
    system_profile: SystemProfile | None = None,
) -> FastAPI:
    """Create the app while deferring optional vision imports until health probes."""
    application = FastAPI(title="ShotSight 2.0", version="0.1.0")
    registry = backend_registry or create_default_registry(
        BackendProbeConfig(
            mlx_model_path=application_settings.mlx_model_path,
            sam3_model_path=application_settings.sam3_model_path,
            cpu_model_path=application_settings.cpu_tracking_model_path,
        )
    )

    runtime = _create_local_runtime(application_settings)
    application.state.runtime = runtime
    application.dependency_overrides[get_video_library_service] = lambda: runtime.video_library
    application.dependency_overrides[get_video_ingestion_service] = lambda: runtime.video_ingestion
    application.dependency_overrides[get_analysis_job_service] = lambda: runtime.analysis_jobs
    application.dependency_overrides[get_deletion_service] = lambda: runtime.deletion
    application.dependency_overrides[get_calibration_service] = lambda: runtime.calibration
    application.dependency_overrides[get_review_service] = lambda: runtime.review
    application.dependency_overrides[get_tracking_service] = lambda: runtime.tracking
    application.dependency_overrides[get_artifact_store] = lambda: runtime.artifact_store
    application.dependency_overrides[get_media_tool] = lambda: runtime.media_tool
    application.dependency_overrides[get_artifact_store_optional] = lambda: runtime.artifact_store

    from shotsight2.presentation import register_presentation

    register_presentation(application)
    register_routes(application)

    application.dependency_overrides[get_settings] = lambda: application_settings
    application.dependency_overrides[get_backend_registry] = lambda: registry
    if system_profile is not None:
        application.dependency_overrides[get_system_profile] = lambda: system_profile

    return application


def _create_local_runtime(application_settings: Settings) -> LocalRuntime:
    data_dir = application_settings.data_dir
    database = SQLiteDatabase(_sqlite_path(application_settings.database_url, data_dir))
    database.migrate()

    artifact_store = FileSystemArtifactStore(ArtifactStoreRoots.under(data_dir))
    media_tool = FFmpegAdapter()
    videos = SQLiteVideoRepository(database)
    runs = SQLiteAnalysisRunRepository(database)
    jobs = SQLiteJobRepository(database)
    artifacts = SQLiteArtifactRepository(database)
    attempts = SQLiteShotAttemptRepository(database)
    players = SQLitePlayerTrackRepository(database)
    segments = SQLiteCameraSegmentRepository(database)
    calibrations = SQLiteCalibrationRepository(database)
    corrections = SQLiteReviewCorrectionRepository(database)
    prompts = SQLiteTrackingPromptRepository(database)
    observations = SQLiteTrackingObservationRepository(database)
    queue = SQLiteWorkerQueue(database)

    video_library = VideoLibraryService(
        videos=videos,
        runs=runs,
        jobs=jobs,
        attempts=attempts,
        artifacts=artifacts,
        players=players,
    )
    video_ingestion = VideoIngestionService(
        media_tool=media_tool,
        video_repository=videos,
        artifact_store=artifact_store,
        limits=VideoIngestionLimits(
            max_upload_bytes=application_settings.max_upload_bytes,
            max_duration_seconds=application_settings.max_video_minutes * 60,
        ),
    )
    analysis_jobs = AnalysisJobService(videos=videos, runs=runs, jobs=jobs, queue=queue)
    deletion = VideoDeletionService(
        videos=videos,
        deletion=SQLiteDeletionRepository(database),
        artifacts=artifacts,
        artifact_store=artifact_store,
    )
    calibration = CalibrationService(segments, calibrations)
    statistics = StatisticsService(attempts, players)
    review = ReviewService(corrections, attempts, players, statistics)
    tracking = TrackingOrchestrator(
        backend=_tracking_backend(application_settings),
        frame_source=OpenCVTrackingFrameSource(data_dir / "runtime-tracking-source.mp4"),
        observations=observations,
        prompts=prompts,
        model_config=ModelConfig(
            model_path=(
                str(application_settings.mlx_model_path)
                if application_settings.tracking_backend == TrackingBackendName.MLX_SAM3.value
                and application_settings.mlx_model_path is not None
                else None
            ),
            device="mps" if application_settings.tracking_backend == TrackingBackendName.MLX_SAM3.value else "cpu",
        ),
    )

    return LocalRuntime(
        database=database,
        artifact_store=artifact_store,
        media_tool=media_tool,
        video_library=video_library,
        video_ingestion=video_ingestion,
        analysis_jobs=analysis_jobs,
        deletion=deletion,
        calibration=calibration,
        review=review,
        tracking=tracking,
    )


def _tracking_backend(application_settings: Settings) -> TrackingBackend:
    """Construct the configured backend without loading optional model weights."""

    if application_settings.tracking_backend == TrackingBackendName.MLX_SAM3.value:
        return MLXSam3ImageBackend()
    return OpenCVTrackingBackend()


def _sqlite_path(database_url: str, data_dir: Path) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return data_dir / "database" / "shotsight2.db"
    raw_path = database_url.removeprefix(prefix)
    path = Path(raw_path)
    return path if path.is_absolute() else path


app = create_app()
