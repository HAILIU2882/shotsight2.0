"""Video list, upload, detail, and deletion routes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from shotsight2.api.deps import (
    get_deletion_service,
    get_video_ingestion_service,
    get_video_library_service,
)
from shotsight2.services.deletion import VideoDeletionService
from shotsight2.services.video_ingestion import VideoIngestionError, VideoIngestionService
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("")
def list_videos(
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
) -> dict[str, Any]:
    """Return all uploaded videos with analysis and storage summaries."""
    result = library.list_videos()
    return dataclasses.asdict(result)


@router.get("/{video_id}")
def get_video(
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
) -> dict[str, Any]:
    """Return detailed projection for one video, or 404 when absent."""
    _validate_identifier(video_id)
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return dataclasses.asdict(detail)


@router.post("", status_code=201)
def upload_video(
    file: UploadFile,
    ingestion: Annotated[VideoIngestionService, Depends(get_video_ingestion_service)],
) -> dict[str, Any]:
    """Stream-upload a video file and register it for analysis.

    Returns 201 with the created video record on success.
    Returns 422 when the file violates size, duration, or format limits.
    """
    from shotsight2.services.video_ingestion import UploadVideoCommand

    filename = file.filename or "upload"
    command = UploadVideoCommand(
        filename=filename,
        chunks=iter([file.file.read()]),
        received_at=datetime.now(UTC),
    )
    try:
        result = ingestion.ingest(command)
    except VideoIngestionError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code.value, "message": str(exc)}) from exc
    return {"video_id": result.video.id, "filename": result.video.filename, "bytes_written": result.bytes_written}


@router.delete("/{video_id}", status_code=204)
def delete_video(
    video_id: str,
    deletion: Annotated[VideoDeletionService, Depends(get_deletion_service)],
) -> None:
    """Permanently delete a video and all its analysis artifacts.

    Returns 409 when the video has an active analysis job.
    Deletion is idempotent: returns 204 even when the video was already deleted.
    """
    _validate_identifier(video_id)
    deletion.delete_video(video_id)


def _validate_identifier(identifier: str) -> None:
    """Reject blank or suspiciously long identifiers before dispatching."""
    if not identifier or not identifier.strip():
        raise HTTPException(status_code=422, detail="Identifier must not be blank")
    if len(identifier) > 128:
        raise HTTPException(status_code=422, detail="Identifier exceeds maximum length")
