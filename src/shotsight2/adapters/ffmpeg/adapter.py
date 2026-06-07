"""Cross-platform FFmpeg adapter with atomic outputs and structured diagnostics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

from shotsight2.adapters.ffmpeg.errors import (
    MediaDiagnostic,
    MediaErrorCategory,
    MediaProcessingError,
)
from shotsight2.domain.media import (
    AudioStreamMetadata,
    ClipRequest,
    ClipResult,
    CommandRecord,
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

_DEFAULT_TIMEOUT_SECONDS = 3_600.0
_DEFAULT_DISK_RESERVE_BYTES = 512 * 1024 * 1024
_MIN_OUTPUT_BYTES = 1


@dataclass(frozen=True, slots=True)
class FFmpegAdapterConfig:
    """Executable, timeout, and storage-safety settings for the adapter."""

    ffmpeg_executable: str = "ffmpeg"
    ffprobe_executable: str = "ffprobe"
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    disk_reserve_bytes: int = _DEFAULT_DISK_RESERVE_BYTES


class FFmpegAdapter:
    """Implement media operations using structured FFmpeg subprocess calls."""

    def __init__(self, config: FFmpegAdapterConfig | None = None) -> None:
        self._config = config or FFmpegAdapterConfig()

    def status(self) -> MediaToolStatus:
        """Return executable availability and version details without raising."""

        return MediaToolStatus(
            ffmpeg=self._tool_status("ffmpeg", self._config.ffmpeg_executable),
            ffprobe=self._tool_status("ffprobe", self._config.ffprobe_executable),
        )

    def probe(self, source: Path) -> MediaMetadata:
        """Probe a media file and parse ffprobe JSON into normalized metadata."""

        self._require_source(source)
        arguments = (
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        )
        completed = self._execute(
            operation="probe",
            executable=self._config.ffprobe_executable,
            arguments=arguments,
        )
        try:
            payload = cast(object, json.loads(completed.stdout))
            return parse_probe_payload(source, payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.UNSUPPORTED_OR_CORRUPT,
                    operation="probe",
                    message=f"ffprobe returned invalid media metadata for {source.name}",
                    command=(self._config.ffprobe_executable, *arguments),
                    stderr=_compact_stderr(completed.stderr or str(error)),
                )
            ) from error

    def create_proxy(self, request: ProxyRequest) -> ProxyResult:
        """Create an orientation-normalized, CFR analysis proxy atomically."""

        source_metadata = self.probe(request.source)
        self._prepare_destination(request.destination, request.overwrite)
        estimated_bytes = max(
            int(source_metadata.duration_seconds * request.profile.estimated_video_bitrate_bps / 8),
            min(source_metadata.size_bytes * 2, 512 * 1024 * 1024),
        )
        self._ensure_disk_space(request.destination, estimated_bytes, "create_proxy")

        scale_filter = (
            "scale="
            f"w='if(gte(iw,ih),min(iw,{request.profile.max_long_edge}),-2)':"
            f"h='if(gte(iw,ih),-2,min(ih,{request.profile.max_long_edge}))',"
            f"fps={_format_number(request.profile.frames_per_second)},setsar=1"
        )
        with self._atomic_destination(request.destination) as temporary:
            arguments = (
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(request.source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                scale_filter,
                "-fps_mode",
                "cfr",
                "-c:v",
                request.profile.video_codec,
                "-preset",
                request.profile.preset,
                "-crf",
                str(request.profile.constant_rate_factor),
                "-pix_fmt",
                request.profile.pixel_format,
                "-c:a",
                request.profile.audio_codec,
                "-b:a",
                request.profile.audio_bitrate,
                "-map_metadata",
                "-1",
                "-metadata:s:v:0",
                "rotate=0",
                "-movflags",
                "+faststart",
                str(temporary),
            )
            self._execute("create_proxy", self._config.ffmpeg_executable, arguments)
            self._validate_output(temporary, "create_proxy")
            command = self._command_record(self._config.ffmpeg_executable, arguments, temporary, request.destination)

        metadata = self.probe(request.destination)
        return ProxyResult(
            path=request.destination,
            metadata=metadata,
            profile=request.profile,
            command=command,
        )

    def extract_frame(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        """Extract one timestamped frame to an image file atomically."""

        metadata = self.probe(request.source)
        if request.timestamp_seconds < 0 or request.timestamp_seconds > metadata.duration_seconds:
            self._raise_invalid(
                "extract_frame",
                f"Timestamp {request.timestamp_seconds} is outside 0..{metadata.duration_seconds}",
            )
        self._prepare_destination(request.destination, request.overwrite)
        self._ensure_disk_space(request.destination, 16 * 1024 * 1024, "extract_frame")

        with self._atomic_destination(request.destination) as temporary:
            arguments = (
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                _format_number(request.timestamp_seconds),
                "-i",
                str(request.source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                str(temporary),
            )
            self._execute("extract_frame", self._config.ffmpeg_executable, arguments)
            self._validate_output(temporary, "extract_frame")
            command = self._command_record(self._config.ffmpeg_executable, arguments, temporary, request.destination)

        return FrameExtractionResult(
            path=request.destination,
            timestamp_seconds=request.timestamp_seconds,
            command=command,
        )

    def create_clip(self, request: ClipRequest) -> ClipResult:
        """Create a replay clip after clamping its range to source bounds."""

        metadata = self.probe(request.source)
        if request.end_seconds <= request.start_seconds:
            self._raise_invalid("create_clip", "Clip end must be greater than clip start")
        actual_start = max(0.0, request.start_seconds)
        actual_end = min(metadata.duration_seconds, request.end_seconds)
        if actual_end <= actual_start:
            self._raise_invalid("create_clip", "Clip range does not overlap the source duration")

        self._prepare_destination(request.destination, request.overwrite)
        estimated_bytes = max(int((actual_end - actual_start) * 8_000_000 / 8), 8 * 1024 * 1024)
        self._ensure_disk_space(request.destination, estimated_bytes, "create_clip")

        with self._atomic_destination(request.destination) as temporary:
            arguments = (
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                _format_number(actual_start),
                "-i",
                str(request.source),
                "-t",
                _format_number(actual_end - actual_start),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporary),
            )
            self._execute("create_clip", self._config.ffmpeg_executable, arguments)
            self._validate_output(temporary, "create_clip")
            command = self._command_record(self._config.ffmpeg_executable, arguments, temporary, request.destination)

        return ClipResult(
            path=request.destination,
            requested_start_seconds=request.start_seconds,
            requested_end_seconds=request.end_seconds,
            actual_start_seconds=actual_start,
            actual_end_seconds=actual_end,
            metadata=self.probe(request.destination),
            command=command,
        )

    def encode_rendered_frames(self, request: RenderedFramesEncodeRequest) -> EncodeResult:
        """Encode a numbered rendered-frame sequence and optional source audio."""

        if request.frames_per_second <= 0:
            self._raise_invalid("encode_rendered_frames", "Frame rate must be positive")
        if request.audio_source is not None:
            self._require_source(request.audio_source)
        self._prepare_destination(request.destination, request.overwrite)
        estimate = max(_sequence_size_estimate(request.frame_pattern) * 2, 32 * 1024 * 1024)
        self._ensure_disk_space(request.destination, estimate, "encode_rendered_frames")

        with self._atomic_destination(request.destination) as temporary:
            arguments_list = [
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                _format_number(request.frames_per_second),
                "-i",
                str(request.frame_pattern),
            ]
            if request.audio_source is not None:
                arguments_list.extend(("-i", str(request.audio_source)))
            arguments_list.extend(("-map", "0:v:0"))
            if request.audio_source is not None:
                arguments_list.extend(("-map", "1:a?", "-shortest", "-c:a", "aac"))
            arguments_list.extend(
                (
                    "-fps_mode",
                    "cfr",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                )
            )
            arguments = tuple(arguments_list)
            self._execute("encode_rendered_frames", self._config.ffmpeg_executable, arguments)
            self._validate_output(temporary, "encode_rendered_frames")
            command = self._command_record(self._config.ffmpeg_executable, arguments, temporary, request.destination)

        return EncodeResult(
            path=request.destination,
            metadata=self.probe(request.destination),
            command=command,
        )

    def encode_overlay(self, request: OverlayEncodeRequest) -> EncodeResult:
        """Composite an overlay video over its source and preserve source audio."""

        source_metadata = self.probe(request.source)
        self.probe(request.overlay)
        self._prepare_destination(request.destination, request.overwrite)
        estimate = max(source_metadata.size_bytes * 2, 32 * 1024 * 1024)
        self._ensure_disk_space(request.destination, estimate, "encode_overlay")

        with self._atomic_destination(request.destination) as temporary:
            arguments = (
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(request.source),
                "-i",
                str(request.overlay),
                "-filter_complex",
                "[0:v:0][1:v:0]overlay=0:0:eof_action=pass:shortest=1[v]",
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporary),
            )
            self._execute("encode_overlay", self._config.ffmpeg_executable, arguments)
            self._validate_output(temporary, "encode_overlay")
            command = self._command_record(self._config.ffmpeg_executable, arguments, temporary, request.destination)

        return EncodeResult(
            path=request.destination,
            metadata=self.probe(request.destination),
            command=command,
        )

    def _tool_status(self, name: str, executable: str) -> ToolStatus:
        resolved = shutil.which(executable)
        if resolved is None:
            return ToolStatus(name=name, available=False, executable=None, version=None)
        try:
            completed = subprocess.run(
                (resolved, "-version"),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ToolStatus(name=name, available=False, executable=Path(resolved), version=None)
        first_line = completed.stdout.splitlines()[0] if completed.returncode == 0 and completed.stdout else None
        return ToolStatus(
            name=name,
            available=completed.returncode == 0,
            executable=Path(resolved),
            version=first_line,
        )

    def _execute(
        self,
        operation: str,
        executable: str,
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        command = (executable, *arguments)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                shell=False,
            )
        except FileNotFoundError as error:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.DEPENDENCY_MISSING,
                    operation=operation,
                    message=f"Required executable is unavailable: {executable}",
                    command=command,
                )
            ) from error
        except subprocess.TimeoutExpired as error:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.TIMEOUT,
                    operation=operation,
                    message=f"Media operation timed out after {self._config.timeout_seconds:g} seconds",
                    command=command,
                    stderr=_compact_stderr(_timeout_stderr(error)),
                )
            ) from error
        except OSError as error:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.SUBPROCESS_FAILED,
                    operation=operation,
                    message=f"Could not start {executable}: {error}",
                    command=command,
                )
            ) from error

        if completed.returncode != 0:
            stderr = _compact_stderr(completed.stderr)
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=_categorize_stderr(stderr),
                    operation=operation,
                    message=f"{operation} failed with exit code {completed.returncode}",
                    command=command,
                    exit_code=completed.returncode,
                    stderr=stderr,
                )
            )
        return completed

    def _prepare_destination(self, destination: Path, overwrite: bool) -> None:
        if destination.exists() and not overwrite:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.DESTINATION_EXISTS,
                    operation="prepare_destination",
                    message=f"Destination already exists: {destination}",
                )
            )
        destination.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _atomic_destination(self, destination: Path) -> Iterator[Path]:
        temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}{destination.suffix}")
        try:
            yield temporary
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_disk_space(self, destination: Path, operation_bytes: int, operation: str) -> None:
        available = shutil.disk_usage(destination.parent).free
        required = operation_bytes + self._config.disk_reserve_bytes
        if available < required:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.DISK_SPACE,
                    operation=operation,
                    message=f"Insufficient disk space: need {required} bytes, have {available} bytes",
                )
            )

    def _require_source(self, source: Path) -> None:
        if not source.is_file():
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.SOURCE_NOT_FOUND,
                    operation="validate_source",
                    message=f"Media source does not exist: {source}",
                )
            )

    def _validate_output(self, output: Path, operation: str) -> None:
        if not output.is_file() or output.stat().st_size < _MIN_OUTPUT_BYTES:
            raise MediaProcessingError(
                MediaDiagnostic(
                    category=MediaErrorCategory.OUTPUT_INVALID,
                    operation=operation,
                    message=f"{operation} did not produce a valid output file",
                )
            )

    def _raise_invalid(self, operation: str, message: str) -> None:
        raise MediaProcessingError(
            MediaDiagnostic(
                category=MediaErrorCategory.INVALID_REQUEST,
                operation=operation,
                message=message,
            )
        )

    @staticmethod
    def _command_record(
        executable: str,
        arguments: Sequence[str],
        temporary: Path,
        destination: Path,
    ) -> CommandRecord:
        recorded = tuple(str(destination) if argument == str(temporary) else argument for argument in arguments)
        return CommandRecord(executable=executable, arguments=recorded)


def parse_probe_payload(source: Path, payload: object) -> MediaMetadata:
    """Parse ffprobe JSON data independently from subprocess execution."""

    root = _mapping(payload, "root")
    streams = _sequence(root.get("streams"), "streams")
    format_data = _mapping(root.get("format"), "format")
    video_data = next(
        (
            _mapping(stream, "video stream")
            for stream in streams
            if _mapping(stream, "stream").get("codec_type") == "video"
        ),
        None,
    )
    if video_data is None:
        raise ValueError("No video stream found")

    width = _integer(video_data.get("width"), "video width")
    height = _integer(video_data.get("height"), "video height")
    rotation = _rotation(video_data)
    display_width, display_height = (height, width) if abs(rotation) % 180 == 90 else (width, height)
    average_fps = _frame_rate(video_data.get("avg_frame_rate"))
    nominal_fps = _frame_rate(video_data.get("r_frame_rate"))
    duration = _optional_float(format_data.get("duration"))
    if duration is None:
        duration = _optional_float(video_data.get("duration"))
    if duration is None or duration <= 0:
        raise ValueError("Media duration is missing or invalid")

    audio_streams = tuple(
        AudioStreamMetadata(
            stream_index=_integer(stream_data.get("index"), "audio stream index"),
            codec=str(stream_data.get("codec_name") or "unknown"),
            sample_rate_hz=_optional_int(stream_data.get("sample_rate")),
            channels=_optional_int(stream_data.get("channels")),
        )
        for stream in streams
        if (stream_data := _mapping(stream, "stream")).get("codec_type") == "audio"
    )
    size_bytes = _optional_int(format_data.get("size"))
    if size_bytes is None:
        size_bytes = source.stat().st_size

    return MediaMetadata(
        path=source,
        format_name=str(format_data.get("format_name") or "unknown"),
        duration_seconds=duration,
        size_bytes=size_bytes,
        bit_rate_bps=_optional_int(format_data.get("bit_rate")),
        video=VideoStreamMetadata(
            stream_index=_integer(video_data.get("index"), "video stream index"),
            codec=str(video_data.get("codec_name") or "unknown"),
            width=width,
            height=height,
            display_width=display_width,
            display_height=display_height,
            average_fps=average_fps,
            nominal_fps=nominal_fps,
            pixel_format=_optional_string(video_data.get("pix_fmt")),
            rotation_degrees=rotation,
            frame_count=_optional_int(video_data.get("nb_frames")),
            is_variable_frame_rate=_is_variable_frame_rate(average_fps, nominal_fps),
        ),
        audio_streams=audio_streams,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return cast(list[object], value)


def _integer(value: object, name: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise ValueError(f"{name} is missing")
    return parsed


def _optional_int(value: object) -> int | None:
    if value in (None, "", "N/A"):
        return None
    return int(cast(Any, value))


def _optional_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    return float(cast(Any, value))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _frame_rate(value: object) -> float:
    if not isinstance(value, str) or value in {"", "0/0", "N/A"}:
        return 0.0
    return float(Fraction(value))


def _rotation(stream: Mapping[str, object]) -> int:
    tags_value = stream.get("tags")
    if isinstance(tags_value, Mapping):
        tags = cast(Mapping[str, object], tags_value)
        tag_rotation = _optional_int(tags.get("rotate"))
        if tag_rotation is not None:
            return tag_rotation % 360
    side_data_value = stream.get("side_data_list")
    if isinstance(side_data_value, list):
        for item in cast(list[object], side_data_value):
            data = _mapping(item, "side data")
            side_rotation = _optional_int(data.get("rotation"))
            if side_rotation is not None:
                return side_rotation % 360
    return 0


def _is_variable_frame_rate(average_fps: float, nominal_fps: float) -> bool:
    if average_fps <= 0 or nominal_fps <= 0:
        return False
    return abs(average_fps - nominal_fps) / max(average_fps, nominal_fps) > 0.01


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _compact_stderr(stderr: str, max_lines: int = 12) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def _categorize_stderr(stderr: str) -> MediaErrorCategory:
    lowered = stderr.lower()
    if "no space left on device" in lowered or "disk full" in lowered:
        return MediaErrorCategory.DISK_SPACE
    corrupt_indicators = (
        "invalid data found",
        "could not find codec parameters",
        "moov atom not found",
        "unknown format",
        "unsupported codec",
    )
    if any(indicator in lowered for indicator in corrupt_indicators):
        return MediaErrorCategory.UNSUPPORTED_OR_CORRUPT
    return MediaErrorCategory.SUBPROCESS_FAILED


def _timeout_stderr(error: subprocess.TimeoutExpired) -> str:
    stderr = error.stderr
    if isinstance(stderr, bytes):
        return stderr.decode(errors="replace")
    return stderr or ""


def _sequence_size_estimate(pattern: Path) -> int:
    parent = pattern.parent
    if not parent.is_dir():
        return 0
    return sum(path.stat().st_size for path in parent.iterdir() if path.is_file())
