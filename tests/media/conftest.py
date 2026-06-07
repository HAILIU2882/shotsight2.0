"""Generated media fixtures for FFmpeg adapter contract tests."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, shell=False)
    if completed.returncode != 0:
        pytest.fail(f"Fixture generation failed: {' '.join(command)}\n{completed.stderr}")


@pytest.fixture(scope="session", autouse=True)
def require_ffmpeg() -> None:
    """Skip integration tests when the local FFmpeg toolchain is unavailable."""

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required for media adapter tests")


@pytest.fixture()
def constant_video(tmp_path: Path) -> Path:
    """Generate a small constant-frame-rate video with audio."""

    output = tmp_path / "constant.mp4"
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=12:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output),
        )
    )
    return output


@pytest.fixture()
def short_video(tmp_path: Path) -> Path:
    """Generate a very short source used for clipping boundary tests."""

    output = tmp_path / "short.mp4"
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=128x72:r=10:d=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        )
    )
    return output


@pytest.fixture()
def variable_rate_video(tmp_path: Path) -> Path:
    """Generate one video containing concatenated 8 FPS and 16 FPS segments."""

    first = tmp_path / "vfr-first.mp4"
    second = tmp_path / "vfr-second.mp4"
    output = tmp_path / "variable-rate.mp4"
    for path, rate in ((first, 8), (second, 16)):
        _run(
            (
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s=160x90:r={rate}:d=1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            )
        )
    concat_file = tmp_path / "segments.txt"
    concat_file.write_text(f"file '{first}'\nfile '{second}'\n", encoding="utf-8")
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output),
        )
    )
    return output


@pytest.fixture()
def rotated_video(tmp_path: Path) -> Path:
    """Generate landscape pixels carrying a 90-degree display rotation."""

    base = tmp_path / "rotation-base.mp4"
    output = tmp_path / "rotated.mp4"
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=96x64:r=10:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(base),
        )
    )
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(base),
            "-c",
            "copy",
            str(output),
        )
    )
    return output


@pytest.fixture()
def corrupt_video(tmp_path: Path) -> Path:
    """Generate a non-media file with a video-like extension."""

    output = tmp_path / "corrupt.mp4"
    output.write_bytes(b"not a real video")
    return output


@pytest.fixture()
def rendered_frames(tmp_path: Path) -> Iterator[Path]:
    """Generate a numbered PNG sequence and return its FFmpeg input pattern."""

    directory = tmp_path / "frames"
    directory.mkdir()
    _run(
        (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x72:r=5:d=1",
            "-frames:v",
            "5",
            str(directory / "frame-%03d.png"),
        )
    )
    yield directory / "frame-%03d.png"

