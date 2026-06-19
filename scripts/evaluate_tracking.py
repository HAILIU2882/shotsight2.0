#!/usr/bin/env python3
"""Run repeatable tracking metrics on the representative local video."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from time import monotonic

import cv2

from shotsight2.adapters.mlx_sam3 import MLXSam3ImageBackend
from shotsight2.adapters.opencv import OpenCVTrackingBackend, OpenCVTrackingFrameSource
from shotsight2.domain.tracking import (
    CameraSegmentInput,
    ModelConfig,
    TrackedObjectClass,
    TrackingPrompt,
    TrackObservation,
)
from shotsight2.ports.tracking import TrackingBackend
from shotsight2.services.tracking import TrackingOrchestrator

DEFAULT_VIDEO = Path("/Users/hailiu/Desktop/bball_pt2.mov")


class _Observations:
    def __init__(self) -> None:
        self.items: list[TrackObservation] = []

    def replace_for_segment(self, segment_id: str, observations: Sequence[TrackObservation]) -> None:
        if any(item.segment_id != segment_id for item in observations):
            raise ValueError("Observation segment mismatch")
        self.items = list(observations)

    def list_for_segment(self, segment_id: str) -> list[TrackObservation]:
        return [item for item in self.items if item.segment_id == segment_id]

    def list_for_run(self, run_id: str) -> list[TrackObservation]:
        del run_id
        return list(self.items)


class _Prompts:
    def __init__(self) -> None:
        self.items: list[TrackingPrompt] = []

    def add(self, prompt: TrackingPrompt) -> None:
        self.items.append(prompt)

    def list_for_segment(self, segment_id: str) -> list[TrackingPrompt]:
        return [item for item in self.items if item.segment_id == segment_id]


def evaluate(
    source: Path,
    *,
    maximum_seconds: float,
    sampling_fps: float,
    backend_name: str = "opencv-cpu",
    model_path: Path | None = None,
) -> dict[str, object]:
    """Evaluate backend coverage and throughput without ground-truth claims."""

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open representative video: {source}")
    try:
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    duration = frame_count / source_fps
    evaluated_duration = min(duration, maximum_seconds)
    segment = CameraSegmentInput(
        "representative-segment",
        "representative-run",
        0,
        evaluated_duration,
        width,
        height,
        source_fps,
    )
    backend = _backend(backend_name)
    model_config = ModelConfig(model_path=None if model_path is None else str(model_path))
    started = monotonic()
    result = TrackingOrchestrator(
        backend,
        OpenCVTrackingFrameSource(source, sampling_fps=sampling_fps),
        _Observations(),
        _Prompts(),
        model_config=model_config,
    ).track_segment(segment)
    elapsed = monotonic() - started
    backend.unload()
    object_counts = {
        object_class.value: sum(item.object_class is object_class for item in result.observations)
        for object_class in TrackedObjectClass
    }
    return {
        "source": str(source),
        "backend": backend_name,
        "source_duration_seconds": duration,
        "evaluated_duration_seconds": evaluated_duration,
        "sampling_fps": sampling_fps,
        "elapsed_seconds": elapsed,
        "processing_fps": result.summary.metrics.expected_frames / elapsed if elapsed else 0,
        "ball_track_coverage": result.summary.metrics.coverage,
        "reinitializations": result.summary.metrics.reinitializations,
        "identity_switches": result.summary.metrics.identity_switches,
        "lost_events": result.summary.metrics.lost_events,
        "occlusion_events": result.summary.metrics.occlusion_events,
        "observation_counts": object_counts,
        "ground_truth_available": False,
    }


def _backend(name: str) -> TrackingBackend:
    if name == "mlx-sam3":
        return MLXSam3ImageBackend()
    if name == "opencv-cpu":
        return OpenCVTrackingBackend()
    raise ValueError(f"Unsupported tracking backend: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--maximum-seconds", type=float, default=30)
    parser.add_argument("--sampling-fps", type=float, default=10)
    parser.add_argument("--backend", choices=("opencv-cpu", "mlx-sam3"), default="opencv-cpu")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.video.exists():
        print(json.dumps({"status": "skipped", "reason": f"Video does not exist: {args.video}"}, indent=2))
        return 0
    report = evaluate(
        args.video,
        maximum_seconds=args.maximum_seconds,
        sampling_fps=args.sampling_fps,
        backend_name=args.backend,
        model_path=args.model_path,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
