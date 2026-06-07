"""Media-processing value objects shared by application ports and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MediaProfileName(StrEnum):
    """Names of supported analysis proxy performance profiles."""

    QUALITY = "quality"
    BALANCED = "balanced"
    SPEED = "speed"


@dataclass(frozen=True, slots=True)
class ProxyProfile:
    """Encoding and sampling policy for an analysis proxy."""

    name: MediaProfileName
    max_long_edge: int
    frames_per_second: float
    constant_rate_factor: int
    preset: str
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    pixel_format: str = "yuv420p"
    estimated_video_bitrate_bps: int = 4_000_000


PROXY_PROFILES: dict[MediaProfileName, ProxyProfile] = {
    MediaProfileName.QUALITY: ProxyProfile(
        name=MediaProfileName.QUALITY,
        max_long_edge=1920,
        frames_per_second=24.0,
        constant_rate_factor=18,
        preset="medium",
        estimated_video_bitrate_bps=8_000_000,
    ),
    MediaProfileName.BALANCED: ProxyProfile(
        name=MediaProfileName.BALANCED,
        max_long_edge=1280,
        frames_per_second=15.0,
        constant_rate_factor=23,
        preset="fast",
        estimated_video_bitrate_bps=4_000_000,
    ),
    MediaProfileName.SPEED: ProxyProfile(
        name=MediaProfileName.SPEED,
        max_long_edge=960,
        frames_per_second=10.0,
        constant_rate_factor=28,
        preset="veryfast",
        estimated_video_bitrate_bps=2_000_000,
    ),
}


def proxy_profile(name: MediaProfileName | str) -> ProxyProfile:
    """Return a supported proxy profile by enum or configuration string."""

    return PROXY_PROFILES[MediaProfileName(name)]


@dataclass(frozen=True, slots=True)
class VideoStreamMetadata:
    """Normalized metadata for the primary video stream."""

    stream_index: int
    codec: str
    width: int
    height: int
    display_width: int
    display_height: int
    average_fps: float
    nominal_fps: float
    pixel_format: str | None
    rotation_degrees: int
    frame_count: int | None
    is_variable_frame_rate: bool


@dataclass(frozen=True, slots=True)
class AudioStreamMetadata:
    """Normalized metadata for an audio stream."""

    stream_index: int
    codec: str
    sample_rate_hz: int | None
    channels: int | None


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    """Container and stream metadata returned by a media probe."""

    path: Path
    format_name: str
    duration_seconds: float
    size_bytes: int
    bit_rate_bps: int | None
    video: VideoStreamMetadata
    audio_streams: tuple[AudioStreamMetadata, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Availability and version information for an external media executable."""

    name: str
    available: bool
    executable: Path | None
    version: str | None


@dataclass(frozen=True, slots=True)
class MediaToolStatus:
    """Combined availability report for FFmpeg and ffprobe."""

    ffmpeg: ToolStatus
    ffprobe: ToolStatus

    @property
    def available(self) -> bool:
        """Return whether both required tools are available."""

        return self.ffmpeg.available and self.ffprobe.available


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """Auditable structured subprocess configuration used for an operation."""

    executable: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProxyRequest:
    """Request to create a normalized analysis proxy."""

    source: Path
    destination: Path
    profile: ProxyProfile
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class ProxyResult:
    """Metadata and execution details for a generated proxy."""

    path: Path
    metadata: MediaMetadata
    profile: ProxyProfile
    command: CommandRecord


@dataclass(frozen=True, slots=True)
class FrameExtractionRequest:
    """Request to extract one frame at a media timestamp."""

    source: Path
    destination: Path
    timestamp_seconds: float
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class FrameExtractionResult:
    """Result of an atomic timestamp-based frame extraction."""

    path: Path
    timestamp_seconds: float
    command: CommandRecord


@dataclass(frozen=True, slots=True)
class ClipRequest:
    """Request to create an encoded replay clip within source bounds."""

    source: Path
    destination: Path
    start_seconds: float
    end_seconds: float
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class ClipResult:
    """Result of a replay clip operation."""

    path: Path
    requested_start_seconds: float
    requested_end_seconds: float
    actual_start_seconds: float
    actual_end_seconds: float
    metadata: MediaMetadata
    command: CommandRecord


@dataclass(frozen=True, slots=True)
class RenderedFramesEncodeRequest:
    """Request to encode an annotated video from a numbered image sequence."""

    frame_pattern: Path
    destination: Path
    frames_per_second: float
    audio_source: Path | None = None
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class OverlayEncodeRequest:
    """Request to composite an annotated overlay video over a source video."""

    source: Path
    overlay: Path
    destination: Path
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class EncodeResult:
    """Result of annotated full-video encoding."""

    path: Path
    metadata: MediaMetadata
    command: CommandRecord
