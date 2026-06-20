"""Production composition root for the independent local analysis worker."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from shotsight2.adapters.ffmpeg import FFmpegAdapter
from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.mlx_sam3 import MLXSam3ImageBackend
from shotsight2.adapters.opencv import OpenCVTrackingBackend
from shotsight2.adapters.persistence import (
    SQLiteAnalysisRunRepository,
    SQLiteBallTrackRepository,
    SQLiteCalibrationRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDatabase,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteTrackingObservationRepository,
    SQLiteTrackingPromptRepository,
    SQLiteVideoRepository,
)
from shotsight2.adapters.sam3_video import Sam31VideoBackend
from shotsight2.adapters.sqlite_queue import SQLiteWorkerQueue
from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.tracking_backends import TrackingBackendName
from shotsight2.ports.tracking import TrackingBackend
from shotsight2.services.analysis_jobs import AnalysisJobService
from shotsight2.services.analysis_pipeline import (
    DEFAULT_STAGE_SPECS,
    AnalysisPipelineOrchestrator,
    PublishPort,
)
from shotsight2.services.artifact_rendering import ArtifactRenderingService
from shotsight2.services.calibration import CalibrationService
from shotsight2.services.production_pipeline import (
    AutomaticCalibrationStage,
    CameraSegmentationStage,
    CourtMappingStage,
    FinalizationStage,
    PreprocessingStage,
    RenderingStage,
    ShotDetectionStage,
    StatisticsStage,
    TrackingStage,
    ValidationStage,
)


def create_production_handler(
    *,
    database: SQLiteDatabase,
    data_dir: Path,
    publisher: PublishPort | None = None,
) -> Callable[[QueueMessage], None]:
    """Build the real job handler without importing FastAPI or web dependencies."""

    database.migrate()
    store = FileSystemArtifactStore(ArtifactStoreRoots.under(data_dir))
    media = FFmpegAdapter()
    videos = SQLiteVideoRepository(database)
    runs = SQLiteAnalysisRunRepository(database)
    jobs = SQLiteJobRepository(database)
    queue = SQLiteWorkerQueue(database)
    segments = SQLiteCameraSegmentRepository(database)
    calibration_repository = SQLiteCalibrationRepository(database)
    observations = SQLiteTrackingObservationRepository(database)
    prompts = SQLiteTrackingPromptRepository(database)
    ball_tracks = SQLiteBallTrackRepository(database)
    players = SQLitePlayerTrackRepository(database)

    job_service = AnalysisJobService(videos=videos, runs=runs, jobs=jobs, queue=queue)
    calibration = CalibrationService(segments, calibration_repository)
    renderer = ArtifactRenderingService(
        artifact_store=store,
        media_tool=media,
        observations=observations,
    )
    runners = (
        ValidationStage(videos, store, media),
        PreprocessingStage(store, media),
        CameraSegmentationStage(store, media, segments),
        AutomaticCalibrationStage(calibration),
        TrackingStage(
            store=store,
            backend_factory=_tracking_backend,
            observations=observations,
            prompts=prompts,
            ball_tracks=ball_tracks,
        ),
        ShotDetectionStage(players),
        CourtMappingStage(),
        RenderingStage(renderer),
        StatisticsStage(),
        FinalizationStage(),
    )
    orchestrator = AnalysisPipelineOrchestrator(
        job_service=job_service,
        run_repository=runs,
        publisher=publisher or runs,
        stages=tuple(zip(DEFAULT_STAGE_SPECS, runners, strict=True)),
        cleanup=_RunArtifactCleanup(store),
    )
    return orchestrator.handle


class _RunArtifactCleanup:
    """Compensate run-owned files when the pipeline cannot publish."""

    def __init__(self, store: FileSystemArtifactStore) -> None:
        self._store = store

    def clean_run_temporaries(
        self,
        video_id: str,
        run_id: str,
        *,
        preserve_diagnostics: bool,
    ) -> None:
        self._store.clean_run_working_files(
            video_id,
            run_id,
            preserve_diagnostics=preserve_diagnostics,
        )


def _tracking_backend(name: str) -> TrackingBackend:
    """Construct exactly the backend recorded by the analysis run."""

    normalized = name.strip().lower()
    if normalized in {TrackingBackendName.OPENCV_CPU.value, "opencv"}:
        return OpenCVTrackingBackend()
    if normalized in {TrackingBackendName.MLX_SAM3.value, "mlx"}:
        return MLXSam3ImageBackend()
    if normalized in {TrackingBackendName.SAM3_CUDA.value, "sam3"}:
        return Sam31VideoBackend()
    raise ValueError(f"Unsupported tracking backend: {name}")


__all__ = ["create_production_handler"]
