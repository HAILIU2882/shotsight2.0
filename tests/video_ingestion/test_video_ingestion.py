"""Upload transaction tests for the Video Ingestion module."""

from __future__ import annotations

import io
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shotsight2.adapters.ffmpeg import FFmpegAdapter, MediaDiagnostic, MediaErrorCategory, MediaProcessingError
from shotsight2.adapters.filesystem import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.adapters.persistence import SQLiteDatabase, SQLiteVideoRepository
from shotsight2.domain import Video, VideoStatus
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.domain.media import (
    AudioStreamMetadata,
    ClipRequest,
    ClipResult,
    EncodeResult,
    FrameExtractionRequest,
    FrameExtractionResult,
    MediaMetadata,
    MediaToolStatus,
    OverlayEncodeRequest,
    ProxyRequest,
    ProxyResult,
    RenderedFramesEncodeRequest,
    ToolStatus,
    VideoStreamMetadata,
)
from shotsight2.ports.media import MediaTool
from shotsight2.services.video_ingestion import (
    UploadVideoCommand,
    VideoIngestionError,
    VideoIngestionErrorCode,
    VideoIngestionLimits,
    VideoIngestionService,
)

NOW = datetime(2026, 6, 8, 4, 30, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path: Path) -> FileSystemArtifactStore:
    """Return an isolated filesystem artifact store."""
    return FileSystemArtifactStore(ArtifactStoreRoots.under(tmp_path / "data"))


def test_valid_upload_streams_to_original_storage_and_persists_metadata(
    tmp_path: Path,
    store: FileSystemArtifactStore,
) -> None:
    """A valid source is preserved byte-for-byte only after metadata is durable."""
    source = _generated_video(tmp_path / "source.mp4")
    database = SQLiteDatabase(tmp_path / "shotsight2.db")
    database.migrate()
    repository = SQLiteVideoRepository(database)
    service = VideoIngestionService(
        media_tool=FFmpegAdapter(),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "integration",
        clock=lambda: NOW,
    )

    result = service.ingest(
        UploadVideoCommand(
            filename="../Same Name.MOV",
            chunks=_read_chunks(source, chunk_size=97),
        )
    )

    assert result.video.id == "video-integration"
    assert result.video.status == "READY"
    assert result.video.original_artifact_id == "upload:video-integration/original.mp4"
    assert result.video.filename == "../Same Name.MOV"
    assert result.video.size_bytes == source.stat().st_size
    assert result.video.duration_seconds == pytest.approx(0.6, abs=0.15)
    assert result.video.width == 96
    assert result.video.height == 54
    assert result.video.codec == "h264"
    assert result.video.audio_codecs == ("aac",)
    assert repository.get(result.video.id) == result.video
    with store.open_read(ArtifactId(result.video.original_artifact_id)) as preserved:
        assert preserved.read() == source.read_bytes()
    assert _stored_files(store, result.video.id) == ["upload:video-integration/original.mp4"]


def test_duplicate_filenames_receive_independent_storage_ids(store: FileSystemArtifactStore) -> None:
    """User filenames never determine permanent upload paths."""
    repository = _MemoryVideoRepository()
    media = _FakeMediaTool(_metadata(Path("upload.tmp"), size_bytes=4))
    identifiers = iter(("first", "second"))
    service = VideoIngestionService(
        media_tool=media,
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: next(identifiers),
        clock=lambda: NOW,
    )

    first = service.ingest(UploadVideoCommand("same.mov", [b"1111"]))
    second = service.ingest(UploadVideoCommand("same.mov", [b"2222"]))

    assert first.video.filename == second.video.filename == "same.mov"
    assert first.video.id == "video-first"
    assert second.video.id == "video-second"
    assert first.video.original_artifact_id != second.video.original_artifact_id
    assert {item.id for item in repository.videos} == {"video-first", "video-second"}


def test_generated_storage_id_is_normalized_before_artifact_paths(store: FileSystemArtifactStore) -> None:
    """Storage identifiers are safe even if an injected ID source is noisy."""
    repository = _MemoryVideoRepository()
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("upload.tmp"), size_bytes=4)),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "VIDEO_../Unsafe Name",
        clock=lambda: NOW,
    )

    result = service.ingest(UploadVideoCommand("same.mov", [b"1111"]))

    assert result.video.id == "video-unsafe-name"
    assert result.video.original_artifact_id == "upload:video-unsafe-name/original.mp4"
    assert _stored_files(store, result.video.id) == ["upload:video-unsafe-name/original.mp4"]


def test_size_limit_stops_stream_and_removes_temporary_files(store: FileSystemArtifactStore) -> None:
    """The upload stream is aborted as soon as the configured byte limit is exceeded."""
    repository = _MemoryVideoRepository()
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("never-probed"), size_bytes=1)),
        video_repository=repository,
        artifact_store=store,
        limits=VideoIngestionLimits(max_upload_bytes=5),
        id_factory=lambda: "too-large",
        clock=lambda: NOW,
    )
    stream = _CountingStream((b"123", b"456", b"789"))

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("huge.mp4", stream))

    assert captured.value.code is VideoIngestionErrorCode.SIZE_LIMIT_EXCEEDED
    assert stream.yielded == 2
    assert repository.videos == []
    assert _stored_files(store, "video-too-large") == []


def test_file_stream_is_read_only_in_configured_bounded_chunks(store: FileSystemArtifactStore) -> None:
    """File-backed uploads never request the entire multipart payload at once."""
    repository = _MemoryVideoRepository()
    stream = _RecordingFile(b"12345678")
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("source.mp4"), size_bytes=8)),
        video_repository=repository,
        artifact_store=store,
        limits=VideoIngestionLimits(chunk_size_hint=3),
        id_factory=lambda: "bounded-file",
        clock=lambda: NOW,
    )

    result = service.ingest(UploadVideoCommand("source.mp4", stream=stream))

    assert result.bytes_written == 8
    assert stream.read_sizes == [3, 3, 3, 3]
    assert len(repository.videos) == 1


def test_oversized_file_stream_leaves_no_artifact_or_database_row(store: FileSystemArtifactStore) -> None:
    """A file stream crossing the byte cap is rolled back before probing."""
    repository = _MemoryVideoRepository()
    stream = _RecordingFile(b"123456")
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("never-probed"), size_bytes=1)),
        video_repository=repository,
        artifact_store=store,
        limits=VideoIngestionLimits(max_upload_bytes=5, chunk_size_hint=3),
        id_factory=lambda: "oversized-file",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("huge.mp4", stream=stream))

    assert captured.value.code is VideoIngestionErrorCode.SIZE_LIMIT_EXCEEDED
    assert stream.read_sizes == [3, 3]
    assert repository.videos == []
    assert _stored_files(store, "video-oversized-file") == []


def test_interrupted_file_stream_leaves_no_artifact_or_database_row(store: FileSystemArtifactStore) -> None:
    """A multipart-file read failure removes every partially written byte."""
    repository = _MemoryVideoRepository()
    stream = _InterruptedFile(b"partial-content")
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("never-probed"), size_bytes=1)),
        video_repository=repository,
        artifact_store=store,
        limits=VideoIngestionLimits(chunk_size_hint=7),
        id_factory=lambda: "interrupted-file",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("source.mp4", stream=stream))

    assert captured.value.code is VideoIngestionErrorCode.STREAM_INTERRUPTED
    assert repository.videos == []
    assert _stored_files(store, "video-interrupted-file") == []


@pytest.mark.parametrize(
    ("error_code", "category"),
    [
        (VideoIngestionErrorCode.UNSUPPORTED_OR_CORRUPT_MEDIA, MediaErrorCategory.UNSUPPORTED_OR_CORRUPT),
        (VideoIngestionErrorCode.MEDIA_TOOL_UNAVAILABLE, MediaErrorCategory.DEPENDENCY_MISSING),
    ],
)
def test_media_probe_failures_keep_diagnostics_and_leave_no_artifacts(
    store: FileSystemArtifactStore,
    error_code: VideoIngestionErrorCode,
    category: MediaErrorCategory,
) -> None:
    """Corrupt media, unsupported codecs, and missing tools are rejected before persistence."""
    repository = _MemoryVideoRepository()
    diagnostic = MediaDiagnostic(
        category=category,
        operation="probe",
        message="ffprobe could not decode stream",
        exit_code=1,
        stderr="unsupported codec detail",
    )
    service = VideoIngestionService(
        media_tool=_FailingProbeMediaTool(diagnostic),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "bad-codec",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("clip.anything", [b"not media"]))

    assert captured.value.code is error_code
    assert captured.value.diagnostic.details["stderr"] == "unsupported codec detail"
    assert repository.videos == []
    assert _stored_files(store, "video-bad-codec") == []


def test_duration_limit_rejects_long_media_without_promoting_original(store: FileSystemArtifactStore) -> None:
    """Sources longer than 30 minutes are rejected after probing."""
    repository = _MemoryVideoRepository()
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("long.mp4"), duration_seconds=1_801)),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "long",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("long.mp4", [b"video"]))

    assert captured.value.code is VideoIngestionErrorCode.DURATION_LIMIT_EXCEEDED
    assert repository.videos == []
    assert _stored_files(store, "video-long") == []


def test_4k_limit_rejects_oversized_media_without_database_row(store: FileSystemArtifactStore) -> None:
    """Display dimensions above the supported 4K envelope are rejected."""
    repository = _MemoryVideoRepository()
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("8k.mp4"), width=7_680, height=4_320)),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "8k",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("8k.mp4", [b"video"]))

    assert captured.value.code is VideoIngestionErrorCode.RESOLUTION_LIMIT_EXCEEDED
    assert repository.videos == []
    assert _stored_files(store, "video-8k") == []


def test_interrupted_stream_removes_partial_upload(store: FileSystemArtifactStore) -> None:
    """Unexpected producer errors cannot leave partial temporary files behind."""
    repository = _MemoryVideoRepository()
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("source.mp4"))),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "interrupted",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("source.mp4", _interrupted_stream()))

    assert captured.value.code is VideoIngestionErrorCode.STREAM_INTERRUPTED
    assert repository.videos == []
    assert _stored_files(store, "video-interrupted") == []


def test_storage_failure_removes_temporary_upload(
    monkeypatch: pytest.MonkeyPatch,
    store: FileSystemArtifactStore,
) -> None:
    """Disk and filesystem failures are reported without a database row."""
    repository = _MemoryVideoRepository()

    def fail_write(_: object, __: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_atomic", fail_write)
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("source.mp4"))),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "disk",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("source.mp4", [b"content"]))

    assert captured.value.code is VideoIngestionErrorCode.STORAGE_FAILED
    assert repository.videos == []
    assert _stored_files(store, "video-disk") == []


def test_persistence_failure_removes_promoted_original(store: FileSystemArtifactStore) -> None:
    """A database failure after promotion rolls back filesystem ownership."""
    repository = _MemoryVideoRepository(fail_create=True)
    service = VideoIngestionService(
        media_tool=_FakeMediaTool(_metadata(Path("source.mp4"), size_bytes=7)),
        video_repository=repository,
        artifact_store=store,
        id_factory=lambda: "db-fails",
        clock=lambda: NOW,
    )

    with pytest.raises(VideoIngestionError) as captured:
        service.ingest(UploadVideoCommand("source.mp4", [b"content"]))

    assert captured.value.code is VideoIngestionErrorCode.PERSISTENCE_FAILED
    assert repository.videos == []
    assert _stored_files(store, "video-db-fails") == []


def _generated_video(destination: Path) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required for ingestion integration tests")
    completed = subprocess.run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=96x54:r=10:d=0.6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=0.6",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(destination),
        ),
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr
    return destination


def _read_chunks(path: Path, *, chunk_size: int) -> Iterable[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            yield chunk


def _stored_files(store: FileSystemArtifactStore, video_id: str) -> list[str]:
    return [str(item.artifact_id) for item in store.inventory_for_video(video_id).artifacts]


def _interrupted_stream() -> Iterable[bytes]:
    yield b"partial"
    raise RuntimeError("client disconnected")


def _metadata(
    path: Path,
    *,
    duration_seconds: float = 10.0,
    size_bytes: int = 4,
    width: int = 1_920,
    height: int = 1_080,
    format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
    video_codec: str = "h264",
) -> MediaMetadata:
    return MediaMetadata(
        path=path,
        format_name=format_name,
        duration_seconds=duration_seconds,
        size_bytes=size_bytes,
        bit_rate_bps=None,
        video=VideoStreamMetadata(
            stream_index=0,
            codec=video_codec,
            width=width,
            height=height,
            display_width=width,
            display_height=height,
            average_fps=30.0,
            nominal_fps=30.0,
            pixel_format="yuv420p",
            rotation_degrees=0,
            frame_count=None,
            is_variable_frame_rate=False,
        ),
        audio_streams=(AudioStreamMetadata(1, "aac", 44_100, 1),),
    )


class _MemoryVideoRepository:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.videos: list[Video] = []
        self.fail_create = fail_create

    def create(self, video: Video) -> None:
        if self.fail_create:
            raise RuntimeError("database locked")
        self.videos.append(video)

    def get(self, video_id: str) -> Video | None:
        return next((video for video in self.videos if video.id == video_id), None)

    def list(self) -> list[Video]:
        return list(self.videos)

    def mark_deleting(self, video_id: str) -> None:
        video = self.get(video_id)
        if video is None:
            raise KeyError(video_id)
        self.videos = [
            replace(item, status=VideoStatus.DELETING) if item.id == video_id else item for item in self.videos
        ]

    def delete(self, video_id: str) -> None:
        self.videos = [video for video in self.videos if video.id != video_id]


class _CountingStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.yielded = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk


class _RecordingFile(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        if size is None or size < 0:
            raise AssertionError("Upload file was read without a byte bound")
        return super().read(size)


class _InterruptedFile(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise OSError("client disconnected")
        return super().read(size)


class _FakeMediaTool:
    def __init__(self, metadata: MediaMetadata) -> None:
        self._metadata = metadata

    def status(self) -> MediaToolStatus:
        return MediaToolStatus(
            ffmpeg=ToolStatus("ffmpeg", True, None, "fake"),
            ffprobe=ToolStatus("ffprobe", True, None, "fake"),
        )

    def probe(self, source: Path) -> MediaMetadata:
        return replace(self._metadata, path=source, size_bytes=source.stat().st_size)

    def create_proxy(self, request: ProxyRequest) -> ProxyResult:
        raise NotImplementedError

    def extract_frame(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        raise NotImplementedError

    def create_clip(self, request: ClipRequest) -> ClipResult:
        raise NotImplementedError

    def encode_rendered_frames(self, request: RenderedFramesEncodeRequest) -> EncodeResult:
        raise NotImplementedError

    def encode_overlay(self, request: OverlayEncodeRequest) -> EncodeResult:
        raise NotImplementedError


class _FailingProbeMediaTool(_FakeMediaTool):
    def __init__(self, diagnostic: MediaDiagnostic) -> None:
        super().__init__(_metadata(Path("failing")))
        self._diagnostic = diagnostic

    def probe(self, source: Path) -> MediaMetadata:
        raise MediaProcessingError(self._diagnostic)


def _requires_media_tool(_: MediaTool) -> None:
    """Type-check fake media tools against the shared protocol."""


_requires_media_tool(_FakeMediaTool(_metadata(Path("type-check"))))
