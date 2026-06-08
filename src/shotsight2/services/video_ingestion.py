"""Upload validation, original-media preservation, and video registration."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import uuid4

from shotsight2.adapters.ffmpeg import MediaErrorCategory, MediaProcessingError
from shotsight2.domain import Video, VideoStatus
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.domain.media import MediaMetadata
from shotsight2.ports.artifacts import ArtifactStore, ArtifactStoreError
from shotsight2.ports.media import MediaTool
from shotsight2.ports.repositories import VideoRepository

DEFAULT_MAX_UPLOAD_BYTES: Final[int] = 1_073_741_824
DEFAULT_MAX_DURATION_SECONDS: Final[float] = 30 * 60
DEFAULT_MAX_4K_LONG_EDGE: Final[int] = 4_096
DEFAULT_MAX_4K_SHORT_EDGE: Final[int] = 2_160
_INGEST_RUN_ID: Final[str] = "ingest"
_TEMPORARY_SUFFIX: Final[str] = ".upload"
_UNSAFE_IDENTIFIER_CHARS = re.compile(r"[^a-z0-9-]+")


class VideoIngestionErrorCode(StrEnum):
    """Stable upload failure categories for routes and UI translation."""

    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    RESOLUTION_LIMIT_EXCEEDED = "resolution_limit_exceeded"
    UNSUPPORTED_OR_CORRUPT_MEDIA = "unsupported_or_corrupt_media"
    MEDIA_TOOL_UNAVAILABLE = "media_tool_unavailable"
    MEDIA_PROBE_FAILED = "media_probe_failed"
    STORAGE_FAILED = "storage_failed"
    PERSISTENCE_FAILED = "persistence_failed"
    STREAM_INTERRUPTED = "stream_interrupted"


@dataclass(frozen=True, slots=True)
class VideoIngestionLimits:
    """Source constraints enforced before a video is registered."""

    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS
    max_4k_long_edge: int = DEFAULT_MAX_4K_LONG_EDGE
    max_4k_short_edge: int = DEFAULT_MAX_4K_SHORT_EDGE
    chunk_size_hint: int = 1024 * 1024

    def __post_init__(self) -> None:
        """Reject nonsensical configuration early."""
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")
        if self.max_4k_long_edge <= 0 or self.max_4k_short_edge <= 0:
            raise ValueError("4K dimension limits must be positive")
        if self.max_4k_long_edge < self.max_4k_short_edge:
            raise ValueError("max_4k_long_edge must be greater than or equal to max_4k_short_edge")
        if self.chunk_size_hint <= 0:
            raise ValueError("chunk_size_hint must be positive")


@dataclass(frozen=True, slots=True)
class UploadVideoCommand:
    """Application command carrying a one-pass byte stream."""

    filename: str
    chunks: Iterable[bytes]
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UploadVideoResult:
    """Successful ingestion output."""

    video: Video
    metadata: MediaMetadata
    bytes_written: int


@dataclass(frozen=True, slots=True)
class IngestionDiagnostic:
    """Structured details retained for rejected uploads."""

    reason: str
    details: dict[str, str | int | float | None] = field(default_factory=dict)


class VideoIngestionError(RuntimeError):
    """Raised when upload validation or registration fails."""

    def __init__(
        self,
        code: VideoIngestionErrorCode,
        message: str,
        *,
        diagnostic: IngestionDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic or IngestionDiagnostic(reason=message)


class VideoIngestionService:
    """Stream, validate, preserve, and register one source video."""

    def __init__(
        self,
        *,
        media_tool: MediaTool,
        video_repository: VideoRepository,
        artifact_store: ArtifactStore,
        limits: VideoIngestionLimits | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._media_tool = media_tool
        self._video_repository = video_repository
        self._artifact_store = artifact_store
        self._limits = limits or VideoIngestionLimits()
        self._id_factory = id_factory or _generate_video_id
        self._clock = clock or _utc_now

    def ingest(self, command: UploadVideoCommand) -> UploadVideoResult:
        """Validate one upload stream and persist its original media."""

        video_id = self._storage_safe_video_id()
        temporary_id: ArtifactId | None = None
        promoted = False
        try:
            temporary_id = self._artifact_store.create_temporary_file(
                video_id,
                _INGEST_RUN_ID,
                suffix=_TEMPORARY_SUFFIX,
            )
            bytes_written = self._write_upload(temporary_id, command.chunks)
            metadata = self._probe(temporary_id)
            self._validate_metadata(metadata)
            destination_id = self._artifact_store.original_id(video_id, _extension_for(metadata))
            original_metadata = self._artifact_store.promote(temporary_id, destination_id)
            promoted = True
            video = self._video_from_metadata(
                video_id=video_id,
                filename=command.filename,
                artifact_id=destination_id,
                metadata=metadata,
                size_bytes=original_metadata.size_bytes,
                created_at=command.received_at or self._clock(),
            )
            self._video_repository.create(video)
        except VideoIngestionError:
            self._cleanup_after_failure(video_id)
            raise
        except (ArtifactStoreError, OSError) as error:
            self._cleanup_after_failure(video_id)
            raise _ingestion_error(
                VideoIngestionErrorCode.STORAGE_FAILED,
                "Could not store uploaded media.",
                error,
            ) from error
        except MediaProcessingError as error:
            self._cleanup_after_failure(video_id)
            raise _media_ingestion_error(error) from error
        except Exception as error:
            self._cleanup_after_failure(video_id)
            if promoted:
                raise _ingestion_error(
                    VideoIngestionErrorCode.PERSISTENCE_FAILED,
                    "Could not persist uploaded video metadata.",
                    error,
                ) from error
            raise _ingestion_error(
                VideoIngestionErrorCode.STREAM_INTERRUPTED,
                "Upload stream ended before it could be stored.",
                error,
            ) from error
        return UploadVideoResult(video=video, metadata=metadata, bytes_written=bytes_written)

    def _write_upload(self, temporary_id: ArtifactId, chunks: Iterable[bytes]) -> int:
        bounded = _BoundedUploadChunks(chunks, self._limits.max_upload_bytes)
        self._artifact_store.write_atomic(temporary_id, bounded)
        return bounded.bytes_seen

    def _probe(self, temporary_id: ArtifactId) -> MediaMetadata:
        with self._artifact_store.local_path(temporary_id) as source:
            return self._media_tool.probe(source)

    def _validate_metadata(self, metadata: MediaMetadata) -> None:
        if metadata.duration_seconds > self._limits.max_duration_seconds:
            raise VideoIngestionError(
                VideoIngestionErrorCode.DURATION_LIMIT_EXCEEDED,
                "Video duration exceeds the 30 minute upload limit.",
                diagnostic=IngestionDiagnostic(
                    reason="duration_limit",
                    details={
                        "duration_seconds": metadata.duration_seconds,
                        "max_duration_seconds": self._limits.max_duration_seconds,
                    },
                ),
            )
        dimensions = sorted((metadata.video.display_width, metadata.video.display_height), reverse=True)
        if dimensions[0] > self._limits.max_4k_long_edge or dimensions[1] > self._limits.max_4k_short_edge:
            raise VideoIngestionError(
                VideoIngestionErrorCode.RESOLUTION_LIMIT_EXCEEDED,
                "Video resolution exceeds the supported 4K upload limit.",
                diagnostic=IngestionDiagnostic(
                    reason="resolution_limit",
                    details={
                        "width": metadata.video.display_width,
                        "height": metadata.video.display_height,
                        "max_long_edge": self._limits.max_4k_long_edge,
                        "max_short_edge": self._limits.max_4k_short_edge,
                    },
                ),
            )

    def _video_from_metadata(
        self,
        *,
        video_id: str,
        filename: str,
        artifact_id: ArtifactId,
        metadata: MediaMetadata,
        size_bytes: int,
        created_at: datetime,
    ) -> Video:
        return Video(
            id=video_id,
            filename=filename,
            original_artifact_id=str(artifact_id),
            size_bytes=size_bytes,
            duration_seconds=metadata.duration_seconds,
            width=metadata.video.display_width,
            height=metadata.video.display_height,
            fps=metadata.video.average_fps,
            codec=metadata.video.codec,
            container=metadata.format_name,
            created_at=_aware_utc(created_at),
            status=VideoStatus.READY,
            rotation_degrees=metadata.video.rotation_degrees,
            audio_codecs=tuple(audio.codec for audio in metadata.audio_streams),
        )

    def _storage_safe_video_id(self) -> str:
        raw = self._id_factory()
        normalized = _UNSAFE_IDENTIFIER_CHARS.sub("-", raw.lower()).strip("-").removeprefix("video-").strip("-")
        return f"video-{normalized or uuid4().hex}"

    def _cleanup_after_failure(self, video_id: str) -> None:
        self._artifact_store.delete_video_tree(video_id)


class _BoundedUploadChunks:
    """One-pass chunk wrapper that aborts as soon as the size limit is crossed."""

    def __init__(self, chunks: Iterable[bytes], max_bytes: int) -> None:
        self._chunks = chunks
        self._max_bytes = max_bytes
        self.bytes_seen = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("Upload chunks must be bytes")
            self.bytes_seen += len(chunk)
            if self.bytes_seen > self._max_bytes:
                raise VideoIngestionError(
                    VideoIngestionErrorCode.SIZE_LIMIT_EXCEEDED,
                    "Upload exceeds the 1 GB size limit.",
                    diagnostic=IngestionDiagnostic(
                        reason="size_limit",
                        details={
                            "bytes_seen": self.bytes_seen,
                            "max_upload_bytes": self._max_bytes,
                        },
                    ),
                )
            if chunk:
                yield chunk


def _generate_video_id() -> str:
    return f"video-{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _extension_for(metadata: MediaMetadata) -> str:
    formats = {item.strip().lower() for item in metadata.format_name.split(",") if item.strip()}
    if formats & {"mov", "mp4", "m4v", "m4a", "3gp", "3g2", "mj2"}:
        return "mp4"
    if "matroska" in formats:
        return "mkv"
    if "avi" in formats:
        return "avi"
    if "webm" in formats:
        return "webm"
    safe = next((item for item in formats if item.replace("_", "").replace("-", "").isalnum()), None)
    return (safe or "video")[:16]


def _media_ingestion_error(error: MediaProcessingError) -> VideoIngestionError:
    category = error.diagnostic.category
    if category is MediaErrorCategory.UNSUPPORTED_OR_CORRUPT:
        code = VideoIngestionErrorCode.UNSUPPORTED_OR_CORRUPT_MEDIA
    elif category is MediaErrorCategory.DEPENDENCY_MISSING:
        code = VideoIngestionErrorCode.MEDIA_TOOL_UNAVAILABLE
    elif category is MediaErrorCategory.DISK_SPACE:
        code = VideoIngestionErrorCode.STORAGE_FAILED
    else:
        code = VideoIngestionErrorCode.MEDIA_PROBE_FAILED
    return VideoIngestionError(
        code,
        error.diagnostic.message,
        diagnostic=IngestionDiagnostic(
            reason=error.diagnostic.category.value,
            details={
                "operation": error.diagnostic.operation,
                "exit_code": error.diagnostic.exit_code,
                "stderr": error.diagnostic.stderr,
            },
        ),
    )


def _ingestion_error(
    code: VideoIngestionErrorCode,
    message: str,
    error: BaseException,
) -> VideoIngestionError:
    return VideoIngestionError(
        code,
        message,
        diagnostic=IngestionDiagnostic(
            reason=type(error).__name__,
            details={"message": str(error)},
        ),
    )
