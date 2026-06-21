"""FastAPI dependency providers — override in tests via app.dependency_overrides."""

from __future__ import annotations

from shotsight2.ports.artifacts import ArtifactStore
from shotsight2.services.analysis_jobs import AnalysisJobService
from shotsight2.services.backend_configuration import AnalysisBackendConfigurationService
from shotsight2.services.calibration import CalibrationService
from shotsight2.services.deletion import VideoDeletionService
from shotsight2.services.review import ReviewService
from shotsight2.services.tracking_repair import TrackingRepairService
from shotsight2.services.video_ingestion import VideoIngestionService
from shotsight2.services.video_library import VideoLibraryService


def get_video_library_service() -> VideoLibraryService:
    """Return the configured video library service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_video_ingestion_service() -> VideoIngestionService:
    """Return the configured video ingestion service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_analysis_job_service() -> AnalysisJobService:
    """Return the configured analysis job service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_deletion_service() -> VideoDeletionService:
    """Return the configured deletion service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_calibration_service() -> CalibrationService:
    """Return the configured calibration service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_review_service() -> ReviewService:
    """Return the configured review service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_tracking_repair_service() -> TrackingRepairService:
    """Return the video-scoped tracking repair service."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_analysis_backend_configuration_service() -> AnalysisBackendConfigurationService:
    """Return the backend catalog and submission validation service."""

    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")


def get_artifact_store() -> ArtifactStore:
    """Return the configured artifact store."""
    raise NotImplementedError("Inject via app.dependency_overrides or create_app()")
