"""Application service for safe, retryable video deletion."""

from __future__ import annotations

import logging

from shotsight2.domain import (
    DeletionFailure,
    DeletionInventory,
    DeletionResult,
    DeletionStatus,
)
from shotsight2.domain.artifacts import ArtifactInventory
from shotsight2.ports.artifacts import ArtifactStore
from shotsight2.ports.repositories import ArtifactRepository, DeletionRepository, VideoRepository

logger = logging.getLogger(__name__)


class DeletionError(RuntimeError):
    """Base class for deletion-service failures."""


class ActiveVideoAnalysisError(DeletionError):
    """Raised when deletion is requested for a video with active analysis work."""

    def __init__(self, video_id: str, active_job_ids: tuple[str, ...]) -> None:
        super().__init__(f"Video {video_id} has active analysis jobs")
        self.video_id = video_id
        self.active_job_ids = active_job_ids


class VideoDeletionService:
    """Build deletion inventories and delete video-owned state safely."""

    def __init__(
        self,
        *,
        videos: VideoRepository,
        deletion: DeletionRepository,
        artifacts: ArtifactRepository,
        artifact_store: ArtifactStore,
    ) -> None:
        self._videos = videos
        self._deletion = deletion
        self._artifacts = artifacts
        self._artifact_store = artifact_store

    def build_inventory(self, video_id: str) -> DeletionInventory:
        """Return the database and filesystem state that deletion would affect."""
        video = self._videos.get(video_id)
        record_counts = self._deletion.inventory_counts(video_id)
        artifact_metadata = tuple(self._artifacts.list_for_video(video_id))
        filesystem_artifacts = self._artifact_store.inventory_for_video(video_id)
        return DeletionInventory(
            video_id=video_id,
            video=video,
            record_counts=record_counts,
            artifact_metadata=artifact_metadata,
            filesystem_artifacts=filesystem_artifacts,
        )

    def delete_video(self, video_id: str) -> DeletionResult:
        """Delete one video and all owned records/artifacts, retrying incomplete cleanup."""
        inventory = self.build_inventory(video_id)
        if inventory.video is None:
            logger.info("Video deletion request was already complete", extra={"video_id": video_id})
            return DeletionResult(video_id=video_id, status=DeletionStatus.ALREADY_DELETED, inventory=inventory)

        try:
            active_jobs = self._deletion.prepare_video_deletion(video_id)
        except KeyError:
            refreshed = self.build_inventory(video_id)
            logger.info("Video deletion request was already complete", extra={"video_id": video_id})
            return DeletionResult(video_id=video_id, status=DeletionStatus.ALREADY_DELETED, inventory=refreshed)

        if active_jobs:
            active_job_ids = tuple(job.id for job in active_jobs)
            logger.info(
                "Rejected video deletion with active analysis jobs",
                extra={"video_id": video_id, "active_job_count": len(active_job_ids)},
            )
            raise ActiveVideoAnalysisError(video_id, active_job_ids)

        logger.info(
            "Prepared video deletion",
            extra={
                "video_id": video_id,
                "record_count": inventory.record_counts.total,
                "artifact_count": len(inventory.filesystem_artifacts.artifacts),
                "total_bytes": inventory.total_bytes,
            },
        )

        try:
            self._artifact_store.delete_video_tree(video_id)
        except Exception as error:
            self._deletion.mark_cleanup_incomplete(video_id)
            remaining = self._remaining_artifacts(video_id)
            failure = DeletionFailure(error_type=type(error).__name__, remaining_artifacts=remaining)
            logger.warning(
                "Video deletion cleanup incomplete",
                extra={
                    "video_id": video_id,
                    "error_type": failure.error_type,
                    "remaining_artifact_count": len(remaining.artifacts),
                    "remaining_bytes": remaining.total_bytes,
                },
            )
            return DeletionResult(
                video_id=video_id,
                status=DeletionStatus.CLEANUP_INCOMPLETE,
                inventory=inventory,
                failure=failure,
            )

        self._deletion.delete_owned_records(video_id)
        logger.info(
            "Completed video deletion",
            extra={
                "video_id": video_id,
                "record_count": inventory.record_counts.total,
                "artifact_count": len(inventory.filesystem_artifacts.artifacts),
                "total_bytes": inventory.total_bytes,
            },
        )
        return DeletionResult(video_id=video_id, status=DeletionStatus.DELETED, inventory=inventory)

    def _remaining_artifacts(self, video_id: str) -> ArtifactInventory:
        try:
            return self._artifact_store.inventory_for_video(video_id)
        except Exception:
            logger.warning("Could not inventory remaining deletion artifacts", extra={"video_id": video_id})
            return ArtifactInventory(video_id=video_id, artifacts=(), total_bytes=0)
