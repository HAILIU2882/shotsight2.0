"""SQLite persistence adapter and repository implementations."""

from shotsight2.adapters.persistence.database import SQLiteDatabase
from shotsight2.adapters.persistence.repositories import (
    SQLiteAnalysisRunRepository,
    SQLiteArtifactRepository,
    SQLiteBallTrackRepository,
    SQLiteCalibrationRepository,
    SQLiteCameraSegmentRepository,
    SQLiteDeletionRepository,
    SQLiteDiagnosticRepository,
    SQLiteJobRepository,
    SQLitePlayerTrackRepository,
    SQLiteReviewCorrectionRepository,
    SQLiteShotAttemptRepository,
    SQLiteShotLocationRepository,
    SQLiteTrackingObservationRepository,
    SQLiteTrackingPromptRepository,
    SQLiteVideoRepository,
)

__all__ = [
    "SQLiteAnalysisRunRepository",
    "SQLiteArtifactRepository",
    "SQLiteBallTrackRepository",
    "SQLiteCalibrationRepository",
    "SQLiteCameraSegmentRepository",
    "SQLiteDatabase",
    "SQLiteDeletionRepository",
    "SQLiteDiagnosticRepository",
    "SQLiteJobRepository",
    "SQLitePlayerTrackRepository",
    "SQLiteReviewCorrectionRepository",
    "SQLiteShotAttemptRepository",
    "SQLiteShotLocationRepository",
    "SQLiteTrackingObservationRepository",
    "SQLiteTrackingPromptRepository",
    "SQLiteVideoRepository",
]
