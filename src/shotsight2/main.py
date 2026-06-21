"""FastAPI entrypoint for the ShotSight 2.0 local web application."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI

from shotsight2.adapters.backend_probes import (
    BackendProbeConfig,
    BackendRegistry,
    create_default_registry,
    inspect_system_profile,
)
from shotsight2.adapters.ffmpeg import FFmpegAdapter
from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
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
    SQLiteVideoRepository,
)
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.api import register_routes
from shotsight2.api.deps import (
    get_analysis_backend_configuration_service,
    get_analysis_job_service,
    get_artifact_store,
    get_calibration_service,
    get_deletion_service,
    get_review_service,
    get_tracking_repair_service,
    get_video_ingestion_service,
    get_video_library_service,
)
from shotsight2.api.routers.health import (
    get_artifact_store_optional,
    get_backend_registry,
    get_media_tool,
    get_product_readiness_service,
    get_settings,
    get_system_profile,
)
from shotsight2.config import Settings, settings
from shotsight2.domain.tracking_backends import SystemProfile
from shotsight2.services import (
    AnalysisJobService,
    CalibrationService,
    StatisticsService,
    VideoDeletionService,
    VideoIngestionLimits,
    VideoIngestionService,
    VideoLibraryService,
)
from shotsight2.services.backend_configuration import AnalysisBackendConfigurationService
from shotsight2.services.readiness import ProductReadinessService
from shotsight2.services.review import ReviewService
from shotsight2.services.tracking_repair import TrackingRepairService


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
    tracking_repair: TrackingRepairService
    backend_configuration: AnalysisBackendConfigurationService
    worker_queue: SQLiteWorkerQueue
    readiness: ProductReadinessService


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

    profile = system_profile or inspect_system_profile()
    runtime = _create_local_runtime(application_settings, registry, profile)
    application.state.runtime = runtime
    application.dependency_overrides[get_video_library_service] = lambda: runtime.video_library
    application.dependency_overrides[get_video_ingestion_service] = lambda: runtime.video_ingestion
    application.dependency_overrides[get_analysis_job_service] = lambda: runtime.analysis_jobs
    application.dependency_overrides[get_deletion_service] = lambda: runtime.deletion
    application.dependency_overrides[get_calibration_service] = lambda: runtime.calibration
    application.dependency_overrides[get_review_service] = lambda: runtime.review
    application.dependency_overrides[get_tracking_repair_service] = lambda: runtime.tracking_repair
    application.dependency_overrides[get_analysis_backend_configuration_service] = lambda: runtime.backend_configuration
    application.dependency_overrides[get_artifact_store] = lambda: runtime.artifact_store
    application.dependency_overrides[get_media_tool] = lambda: runtime.media_tool
    application.dependency_overrides[get_artifact_store_optional] = lambda: runtime.artifact_store
    application.dependency_overrides[get_product_readiness_service] = lambda: runtime.readiness

    from shotsight2.presentation import register_presentation

    register_presentation(application)
    register_routes(application)

    application.dependency_overrides[get_settings] = lambda: application_settings
    application.dependency_overrides[get_backend_registry] = lambda: registry
    application.dependency_overrides[get_system_profile] = lambda: profile

    return application


def _create_local_runtime(
    application_settings: Settings,
    backend_registry: BackendRegistry,
    system_profile: SystemProfile,
) -> LocalRuntime:
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
    queue = SQLiteWorkerQueue(database)
    readiness = ProductReadinessService(
        queue,
        stale_after=timedelta(seconds=application_settings.worker_readiness_stale_seconds),
    )

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
    tracking_repair = TrackingRepairService(videos, runs, segments)
    backend_configuration = AnalysisBackendConfigurationService(
        backend_registry,
        system_profile,
        application_settings.tracking_backend,
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
        tracking_repair=tracking_repair,
        backend_configuration=backend_configuration,
        worker_queue=queue,
        readiness=readiness,
    )


def _sqlite_path(database_url: str, data_dir: Path) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return data_dir / "database" / "shotsight2.db"
    raw_path = database_url.removeprefix(prefix)
    path = Path(raw_path)
    return path if path.is_absolute() else path


app = create_app()
