"""Contract and integration tests for the FFmpeg media adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from shotsight2.adapters.ffmpeg import (
    FFmpegAdapter,
    FFmpegAdapterConfig,
    MediaErrorCategory,
    MediaProcessingError,
)
from shotsight2.adapters.ffmpeg.adapter import parse_probe_payload
from shotsight2.domain.media import (
    ClipRequest,
    FrameExtractionRequest,
    MediaProfileName,
    OverlayEncodeRequest,
    ProxyRequest,
    RenderedFramesEncodeRequest,
    proxy_profile,
)
from shotsight2.ports.media import MediaTool


def test_adapter_satisfies_media_tool_contract() -> None:
    """The adapter exposes the application-facing media port operations."""

    adapter: MediaTool = FFmpegAdapter()

    assert callable(adapter.probe)
    assert callable(adapter.create_proxy)
    assert callable(adapter.extract_frame)
    assert callable(adapter.create_clip)
    assert callable(adapter.encode_rendered_frames)
    assert callable(adapter.encode_overlay)


def test_profiles_expose_quality_balanced_and_speed_tradeoffs() -> None:
    """Profiles reduce temporal and spatial density in the expected order."""

    quality = proxy_profile("quality")
    balanced = proxy_profile(MediaProfileName.BALANCED)
    speed = proxy_profile("speed")

    assert quality.max_long_edge > balanced.max_long_edge > speed.max_long_edge
    assert quality.frames_per_second > balanced.frames_per_second > speed.frames_per_second
    assert quality.constant_rate_factor < balanced.constant_rate_factor < speed.constant_rate_factor


def test_status_reports_tool_paths_and_versions() -> None:
    """Installed FFmpeg tools are reported with executable paths and versions."""

    status = FFmpegAdapter().status()

    assert status.available
    assert status.ffmpeg.executable is not None
    assert status.ffmpeg.version is not None
    assert status.ffprobe.executable is not None
    assert status.ffprobe.version is not None


def test_status_reports_missing_executables_without_raising() -> None:
    """Capability discovery remains safe when dependencies are absent."""

    adapter = FFmpegAdapter(
        FFmpegAdapterConfig(
            ffmpeg_executable="missing-shotsight-ffmpeg",
            ffprobe_executable="missing-shotsight-ffprobe",
        )
    )

    status = adapter.status()

    assert not status.available
    assert not status.ffmpeg.available
    assert not status.ffprobe.available


def test_probe_parses_constant_video_and_audio(constant_video: Path) -> None:
    """ffprobe JSON becomes typed container, video, and audio metadata."""

    metadata = FFmpegAdapter().probe(constant_video)

    assert metadata.path == constant_video
    assert metadata.duration_seconds == pytest.approx(2.0, abs=0.1)
    assert metadata.video.width == 160
    assert metadata.video.height == 90
    assert metadata.video.average_fps == pytest.approx(12.0)
    assert metadata.video.codec == "h264"
    assert not metadata.video.is_variable_frame_rate
    assert metadata.audio_streams[0].codec == "aac"


def test_probe_parses_rotation_and_display_dimensions(rotated_video: Path) -> None:
    """Rotation side data is reflected in normalized display dimensions."""

    metadata = FFmpegAdapter().probe(rotated_video)

    assert metadata.video.width == 96
    assert metadata.video.height == 64
    assert metadata.video.rotation_degrees == 90
    assert metadata.video.display_width == 64
    assert metadata.video.display_height == 96


def test_parse_probe_payload_accepts_rotation_tag_and_stream_duration(tmp_path: Path) -> None:
    """The parser supports common ffprobe field variants without a subprocess."""

    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"x")
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24/1",
                "r_frame_rate": "30/1",
                "duration": "1.5",
                "tags": {"rotate": "270"},
            }
        ],
        "format": {"format_name": "mov", "size": "1"},
    }

    metadata = parse_probe_payload(source, payload)

    assert metadata.duration_seconds == 1.5
    assert metadata.video.rotation_degrees == 270
    assert metadata.video.display_width == 1080
    assert metadata.video.is_variable_frame_rate


def test_corrupt_probe_returns_structured_diagnostics(corrupt_video: Path) -> None:
    """Corrupt input is categorized and includes the structured command."""

    with pytest.raises(MediaProcessingError) as captured:
        FFmpegAdapter().probe(corrupt_video)

    diagnostic = captured.value.diagnostic
    assert diagnostic.category is MediaErrorCategory.UNSUPPORTED_OR_CORRUPT
    assert diagnostic.operation == "probe"
    assert diagnostic.exit_code != 0
    assert diagnostic.command[0] == "ffprobe"
    assert diagnostic.stderr


def test_missing_probe_executable_returns_dependency_error(constant_video: Path) -> None:
    """A missing ffprobe executable produces an actionable dependency error."""

    adapter = FFmpegAdapter(FFmpegAdapterConfig(ffprobe_executable="missing-shotsight-ffprobe"))

    with pytest.raises(MediaProcessingError) as captured:
        adapter.probe(constant_video)

    assert captured.value.diagnostic.category is MediaErrorCategory.DEPENDENCY_MISSING


@pytest.mark.parametrize("profile_name", list(MediaProfileName))
def test_create_proxy_records_profile_and_normalized_metadata(
    constant_video: Path,
    tmp_path: Path,
    profile_name: MediaProfileName,
) -> None:
    """Every profile creates an auditable CFR proxy without upscaling."""

    destination = tmp_path / f"{profile_name}.mp4"
    profile = proxy_profile(profile_name)

    result = FFmpegAdapter().create_proxy(ProxyRequest(constant_video, destination, profile))

    assert result.path == destination
    assert result.metadata.video.width == 160
    assert result.metadata.video.height == 90
    assert result.metadata.video.average_fps == pytest.approx(profile.frames_per_second, rel=0.02)
    assert not result.metadata.video.is_variable_frame_rate
    assert result.metadata.video.codec == "h264"
    assert result.profile == profile
    assert result.command.arguments[-1] == str(destination)
    assert ".tmp" not in " ".join(result.command.arguments)


def test_proxy_normalizes_variable_rate_video(variable_rate_video: Path, tmp_path: Path) -> None:
    """A VFR source becomes a configured constant-frame-rate proxy."""

    adapter = FFmpegAdapter()
    source_metadata = adapter.probe(variable_rate_video)
    profile = proxy_profile("balanced")

    result = adapter.create_proxy(
        ProxyRequest(
            source=variable_rate_video,
            destination=tmp_path / "vfr-proxy.mp4",
            profile=profile,
        )
    )

    assert source_metadata.video.is_variable_frame_rate
    assert not result.metadata.video.is_variable_frame_rate
    assert result.metadata.video.average_fps == pytest.approx(profile.frames_per_second, rel=0.02)


def test_proxy_applies_rotation_and_clears_orientation_metadata(rotated_video: Path, tmp_path: Path) -> None:
    """Proxy pixels have display orientation applied and no residual rotation."""

    result = FFmpegAdapter().create_proxy(
        ProxyRequest(
            source=rotated_video,
            destination=tmp_path / "rotated-proxy.mp4",
            profile=proxy_profile("balanced"),
        )
    )

    assert result.metadata.video.width == 64
    assert result.metadata.video.height == 96
    assert result.metadata.video.rotation_degrees == 0
    assert result.metadata.video.display_width == 64
    assert result.metadata.video.display_height == 96


def test_proxy_downscales_large_source(tmp_path: Path) -> None:
    """Sources exceeding a profile's long edge are reduced proportionally."""

    source = tmp_path / "large.mp4"
    subprocess.run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:r=5:d=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ),
        check=True,
        shell=False,
    )

    result = FFmpegAdapter().create_proxy(
        ProxyRequest(
            source=source,
            destination=tmp_path / "small.mp4",
            profile=proxy_profile("speed"),
        )
    )

    assert result.metadata.video.width == 960
    assert result.metadata.video.height == 540


def test_extract_frame_at_timestamp_is_atomic(constant_video: Path, tmp_path: Path) -> None:
    """Timestamp extraction creates only the requested final image."""

    destination = tmp_path / "frame.jpg"
    result = FFmpegAdapter().extract_frame(FrameExtractionRequest(constant_video, destination, timestamp_seconds=0.75))

    assert result.path == destination
    assert destination.stat().st_size > 0
    assert result.command.arguments[-1] == str(destination)
    assert list(tmp_path.glob(".*.jpg")) == []


def test_extract_frame_rejects_timestamp_outside_source(constant_video: Path, tmp_path: Path) -> None:
    """Frame extraction rejects negative and past-end timestamps."""

    with pytest.raises(MediaProcessingError) as captured:
        FFmpegAdapter().extract_frame(
            FrameExtractionRequest(constant_video, tmp_path / "frame.png", timestamp_seconds=10)
        )

    assert captured.value.diagnostic.category is MediaErrorCategory.INVALID_REQUEST


def test_clip_is_bounded_to_short_source(short_video: Path, tmp_path: Path) -> None:
    """Replay ranges are clamped to zero and the source duration."""

    result = FFmpegAdapter().create_clip(
        ClipRequest(
            source=short_video,
            destination=tmp_path / "clip.mp4",
            start_seconds=-2,
            end_seconds=20,
        )
    )

    assert result.actual_start_seconds == 0
    assert result.actual_end_seconds == pytest.approx(0.6, abs=0.1)
    assert result.metadata.duration_seconds <= 0.7
    assert result.path.exists()


def test_clip_rejects_inverted_range(short_video: Path, tmp_path: Path) -> None:
    """Replay clipping rejects an end timestamp before its start."""

    with pytest.raises(MediaProcessingError) as captured:
        FFmpegAdapter().create_clip(ClipRequest(short_video, tmp_path / "clip.mp4", 1, 0))

    assert captured.value.diagnostic.category is MediaErrorCategory.INVALID_REQUEST


def test_encode_rendered_frames_with_optional_audio(
    rendered_frames: Path,
    constant_video: Path,
    tmp_path: Path,
) -> None:
    """Rendered images can become a playable annotated video with source audio."""

    result = FFmpegAdapter().encode_rendered_frames(
        RenderedFramesEncodeRequest(
            frame_pattern=rendered_frames,
            destination=tmp_path / "rendered.mp4",
            frames_per_second=5,
            audio_source=constant_video,
        )
    )

    assert result.path.exists()
    assert result.metadata.video.width == 128
    assert result.metadata.video.height == 72
    assert result.metadata.video.average_fps == pytest.approx(5)
    assert result.metadata.audio_streams


def test_encode_overlay_composites_two_videos(constant_video: Path, short_video: Path, tmp_path: Path) -> None:
    """An overlay video can be composited into a full annotated output."""

    result = FFmpegAdapter().encode_overlay(
        OverlayEncodeRequest(
            source=constant_video,
            overlay=short_video,
            destination=tmp_path / "overlay.mp4",
        )
    )

    assert result.path.exists()
    assert result.metadata.video.width == 160
    assert result.metadata.video.height == 90
    assert result.metadata.duration_seconds == pytest.approx(2.0, abs=0.15)


def test_existing_destination_requires_explicit_overwrite(constant_video: Path, tmp_path: Path) -> None:
    """Media operations cannot silently replace existing artifacts."""

    destination = tmp_path / "proxy.mp4"
    destination.write_bytes(b"existing")

    with pytest.raises(MediaProcessingError) as captured:
        FFmpegAdapter().create_proxy(ProxyRequest(constant_video, destination, proxy_profile("speed")))

    assert captured.value.diagnostic.category is MediaErrorCategory.DESTINATION_EXISTS


def test_failed_encode_leaves_no_partial_artifact(constant_video: Path, tmp_path: Path) -> None:
    """Atomic output cleanup removes temporary files after FFmpeg failure."""

    destination = tmp_path / "failed.mp4"
    adapter = FFmpegAdapter(FFmpegAdapterConfig(ffmpeg_executable="ffprobe"))

    with pytest.raises(MediaProcessingError) as captured:
        adapter.create_proxy(ProxyRequest(constant_video, destination, proxy_profile("speed")))

    assert captured.value.diagnostic.category is MediaErrorCategory.SUBPROCESS_FAILED
    assert not destination.exists()
    assert list(tmp_path.glob(".*.mp4")) == []


def test_disk_space_is_checked_before_proxy_encoding(constant_video: Path, tmp_path: Path) -> None:
    """A storage shortfall fails before FFmpeg creates an output."""

    destination = tmp_path / "proxy.mp4"
    adapter = FFmpegAdapter(FFmpegAdapterConfig(disk_reserve_bytes=1024))
    tiny_usage = shutil._ntuple_diskusage(total=100, used=99, free=1)

    with (
        patch("shotsight2.adapters.ffmpeg.adapter.shutil.disk_usage", return_value=tiny_usage),
        pytest.raises(MediaProcessingError) as captured,
    ):
        adapter.create_proxy(ProxyRequest(constant_video, destination, proxy_profile("quality")))

    assert captured.value.diagnostic.category is MediaErrorCategory.DISK_SPACE
    assert not destination.exists()


def test_subprocess_calls_never_enable_shell(constant_video: Path) -> None:
    """The adapter passes commands as argument sequences with shell disabled."""

    shell_values: list[bool] = []
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 160,
                "height": 90,
                "avg_frame_rate": "12/1",
                "r_frame_rate": "12/1",
            }
        ],
        "format": {
            "format_name": "mov,mp4",
            "duration": "2.0",
            "size": str(constant_video.stat().st_size),
        },
    }

    def recording_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        shell_values.append(bool(kwargs.get("shell")))
        return subprocess.CompletedProcess(
            args=("ffprobe",),
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    with patch("shotsight2.adapters.ffmpeg.adapter.subprocess.run", side_effect=recording_run):
        FFmpegAdapter().probe(constant_video)

    assert shell_values == [False]
