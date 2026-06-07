"""Deterministic generated videos for camera segmentation tests."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
import pytest

VideoFactory = Callable[[str, float], Path]


def _scene_a() -> np.ndarray:
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    image[:] = (34, 92, 38)
    cv2.rectangle(image, (12, 12), (207, 107), (235, 235, 235), 2)
    cv2.line(image, (110, 12), (110, 107), (235, 235, 235), 2)
    cv2.circle(image, (45, 60), 22, (40, 40, 200), -1)
    cv2.putText(image, "A", (145, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (240, 220, 40), 3)
    return image


def _scene_b() -> np.ndarray:
    image = np.zeros((120, 220, 3), dtype=np.uint8)
    image[:] = (145, 55, 35)
    for x_value in range(0, 220, 20):
        cv2.line(image, (x_value, 0), (219 - x_value, 119), (35, 180, 220), 2)
    cv2.rectangle(image, (70, 25), (155, 95), (220, 220, 220), 4)
    cv2.putText(image, "B", (92, 77), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 4)
    return image


def _shifted(scene: np.ndarray, shift_x: float, shift_y: float = 0.0) -> np.ndarray:
    transform = np.array([[1.0, 0.0, shift_x], [0.0, 1.0, shift_y]], dtype=np.float32)
    return cv2.warpAffine(
        scene,
        transform,
        (scene.shape[1], scene.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )


def _render_scenario(name: str, timestamp: float) -> np.ndarray:
    scene_a = _scene_a()
    if name == "fixed":
        frame = scene_a.copy()
        ball_x = 25 + round((timestamp % 2.0) * 35)
        cv2.circle(frame, (ball_x, 95), 4, (15, 120, 245), -1)
        return frame
    if name == "setup":
        shift = min(42.0, timestamp * 21.0)
        return _shifted(scene_a, shift)
    if name == "angle":
        return scene_a if timestamp < 3.0 else _scene_b()
    if name == "bumps":
        for start in (2.0, 4.5):
            if start <= timestamp < start + 0.9:
                phase = (timestamp - start) / 0.9
                return _shifted(scene_a, 28.0 * np.sin(phase * np.pi * 4))
        return scene_a
    if name == "hard-cut":
        return scene_a if timestamp < 3.0 else _scene_b()
    if name == "short":
        return scene_a
    raise ValueError(f"Unknown generated scenario: {name}")


@pytest.fixture()
def video_factory(tmp_path: Path) -> VideoFactory:
    """Render a named camera scenario and encode it as a CFR analysis proxy."""

    def create(name: str, duration_seconds: float) -> Path:
        frames_per_second = 10
        frame_count = max(1, round(duration_seconds * frames_per_second))
        frame_directory = tmp_path / f"{name}-frames"
        frame_directory.mkdir()
        for index in range(frame_count):
            timestamp = index / frames_per_second
            frame = _render_scenario(name, timestamp)
            written = cv2.imwrite(str(frame_directory / f"frame-{index:04d}.png"), frame)
            assert written
        destination = tmp_path / f"{name}.mp4"
        completed = subprocess.run(
            (
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                str(frames_per_second),
                "-i",
                str(frame_directory / "frame-%04d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(destination),
            ),
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        assert completed.returncode == 0, completed.stderr
        return destination

    return create
