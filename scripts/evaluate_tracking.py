#!/usr/bin/env python3
"""Run repeatable tracking metrics on the representative local video."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, cast

import cv2

from shotsight2.adapters.mlx_sam3 import MLXSam3ImageBackend
from shotsight2.adapters.opencv import OpenCVTrackingBackend, OpenCVTrackingFrameSource
from shotsight2.domain.persistence import JsonObject
from shotsight2.domain.tracking import (
    CameraSegmentInput,
    ModelConfig,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingEventKind,
    TrackingPrompt,
    TrackObservation,
)
from shotsight2.ports.tracking import TrackingBackend
from shotsight2.services.tracking import TrackingOrchestrator

DEFAULT_VIDEO = Path("/Users/hailiu/Desktop/bball_pt2.mov")


@dataclass(frozen=True, slots=True)
class _VideoMetadata:
    fps: float
    width: int
    height: int
    frame_count: int

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps


@dataclass(frozen=True, slots=True)
class _ShotLabel:
    attempt_id: str
    release_seconds: float


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
    model_options: JsonObject | None = None,
) -> dict[str, object]:
    """Evaluate backend coverage and throughput without ground-truth claims."""

    metadata = _video_metadata(source)
    duration = metadata.duration_seconds
    evaluated_duration = min(duration, maximum_seconds)
    segment = CameraSegmentInput(
        "representative-segment",
        "representative-run",
        0,
        evaluated_duration,
        metadata.width,
        metadata.height,
        metadata.fps,
    )
    backend = _backend(backend_name)
    model_config = ModelConfig(
        model_path=None if model_path is None else str(model_path),
        options=model_options or {},
    )
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


def evaluate_labeled_windows(
    source: Path,
    labels_path: Path,
    *,
    sampling_fps: float,
    window_before_seconds: float,
    window_after_seconds: float,
    release_window_seconds: float,
    shot_ids: Sequence[str] = (),
    maximum_shots: int | None = None,
    model_path: Path | None = None,
    model_options: JsonObject | None = None,
) -> dict[str, object]:
    """Run MLX SAM 3 only in selected human-labeled release windows."""

    if sampling_fps <= 0 or window_before_seconds < 0 or window_after_seconds <= 0:
        raise ValueError("Sampling FPS and labeled-window durations must be positive")
    if release_window_seconds < 0:
        raise ValueError("release_window_seconds cannot be negative")
    metadata = _video_metadata(source)
    labels = _load_shot_labels(labels_path, shot_ids, maximum_shots)
    backend = MLXSam3ImageBackend()
    backend.load(
        ModelConfig(
            model_path=None if model_path is None else str(model_path),
            options=model_options or {},
        )
    )
    frame_source = OpenCVTrackingFrameSource(source, sampling_fps=sampling_fps)
    started = monotonic()
    windows: list[dict[str, object]] = []
    all_observations: list[TrackObservation] = []
    identity_switches = 0
    evaluated_frames = 0
    try:
        for label in labels:
            start_seconds = max(0.0, label.release_seconds - window_before_seconds)
            end_seconds = min(metadata.duration_seconds, label.release_seconds + window_after_seconds)
            segment = CameraSegmentInput(
                id=f"benchmark-{label.attempt_id}",
                analysis_run_id="labeled-window-benchmark",
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                width=metadata.width,
                height=metadata.height,
                fps=metadata.fps,
            )
            prompt = TrackingPrompt(
                id=f"benchmark-{label.attempt_id}-basketball",
                segment_id=segment.id,
                timestamp_seconds=start_seconds,
                object_class=TrackedObjectClass.BASKETBALL,
                kind=PromptKind.CONCEPT,
                source=PromptSource.AUTOMATIC,
                text="basketball",
            )
            session = backend.start_segment(segment, (prompt,))
            observations: list[TrackObservation] = []
            window_frames = 0
            frame_timestamps: list[float] = []
            for batch in frame_source.batches(segment):
                window_frames += len(batch.frames)
                frame_timestamps.extend(frame.timestamp_seconds for frame in batch.frames)
                result = backend.process_batch(session, batch)
                observations.extend(result.observations)
                identity_switches += sum(
                    event.kind is TrackingEventKind.IDENTITY_SWITCH
                    and event.object_class is TrackedObjectClass.BASKETBALL
                    for event in result.events
                )
            backend.close_segment(session)
            evaluated_frames += window_frames
            all_observations.extend(observations)
            release_start = label.release_seconds - release_window_seconds
            release_end = label.release_seconds + release_window_seconds
            release_observations = tuple(
                item for item in observations if release_start <= item.timestamp_seconds <= release_end
            )
            post_release_observations = tuple(
                item for item in observations if label.release_seconds <= item.timestamp_seconds <= release_end
            )
            release_evaluated_frames = sum(release_start <= item <= release_end for item in frame_timestamps)
            post_release_evaluated_frames = sum(
                label.release_seconds <= item <= release_end for item in frame_timestamps
            )
            release_observed_frames = len({item.frame_index for item in release_observations})
            post_release_observed_frames = len({item.frame_index for item in post_release_observations})
            windows.append(
                {
                    "attempt_id": label.attempt_id,
                    "release_seconds": label.release_seconds,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "evaluated_frames": window_frames,
                    "observed_frames": len({item.frame_index for item in observations}),
                    "basketball_observations": len(observations),
                    "basketball_track_ids": sorted({item.local_track_id for item in observations}),
                    "release_window_observations": len(release_observations),
                    "release_window_hit": bool(release_observations),
                    "release_window_evaluated_frames": release_evaluated_frames,
                    "release_window_observed_frames": release_observed_frames,
                    "release_window_frame_coverage": (
                        release_observed_frames / release_evaluated_frames if release_evaluated_frames else 0.0
                    ),
                    "post_release_observations": len(post_release_observations),
                    "post_release_hit": bool(post_release_observations),
                    "post_release_evaluated_frames": post_release_evaluated_frames,
                    "post_release_observed_frames": post_release_observed_frames,
                    "post_release_frame_coverage": (
                        post_release_observed_frames / post_release_evaluated_frames
                        if post_release_evaluated_frames
                        else 0.0
                    ),
                }
            )
    finally:
        backend.unload()
    elapsed = monotonic() - started
    observed_frames = len({(item.segment_id, item.frame_index) for item in all_observations})
    release_hits = sum(bool(window["release_window_hit"]) for window in windows)
    release_evaluated_frames = sum(cast(int, window["release_window_evaluated_frames"]) for window in windows)
    release_observed_frames = sum(cast(int, window["release_window_observed_frames"]) for window in windows)
    post_release_hits = sum(bool(window["post_release_hit"]) for window in windows)
    post_release_evaluated_frames = sum(cast(int, window["post_release_evaluated_frames"]) for window in windows)
    post_release_observed_frames = sum(cast(int, window["post_release_observed_frames"]) for window in windows)
    return {
        "source": str(source),
        "labels": str(labels_path),
        "backend": "mlx-sam3",
        "sampling_fps": sampling_fps,
        "window_before_seconds": window_before_seconds,
        "window_after_seconds": window_after_seconds,
        "release_window_seconds": release_window_seconds,
        "evaluated_shots": len(windows),
        "evaluated_frames": evaluated_frames,
        "observed_frames": observed_frames,
        "ball_track_coverage": observed_frames / evaluated_frames if evaluated_frames else 0.0,
        "release_window_hits": release_hits,
        "release_window_coverage": release_hits / len(windows) if windows else 0.0,
        "release_window_frame_coverage": (
            release_observed_frames / release_evaluated_frames if release_evaluated_frames else 0.0
        ),
        "post_release_hits": post_release_hits,
        "post_release_window_coverage": post_release_hits / len(windows) if windows else 0.0,
        "post_release_frame_coverage": (
            post_release_observed_frames / post_release_evaluated_frames if post_release_evaluated_frames else 0.0
        ),
        "basketball_observations": len(all_observations),
        "basketball_track_ids": len({(item.segment_id, item.local_track_id) for item in all_observations}),
        "identity_switches": identity_switches,
        "elapsed_seconds": elapsed,
        "windows": windows,
        "ground_truth_available": True,
        "scope": "adapter-level basketball observations; shot lifecycle attempts are not evaluated",
        "model_options": model_options or {},
    }


def _video_metadata(source: Path) -> _VideoMetadata:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open representative video: {source}")
    try:
        metadata = _VideoMetadata(
            fps=float(capture.get(cv2.CAP_PROP_FPS)),
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        )
    finally:
        capture.release()
    if metadata.fps <= 0 or metadata.width <= 0 or metadata.height <= 0 or metadata.frame_count <= 0:
        raise RuntimeError(f"Representative video has invalid metadata: {source}")
    return metadata


def _load_shot_labels(
    labels_path: Path,
    shot_ids: Sequence[str],
    maximum_shots: int | None,
) -> tuple[_ShotLabel, ...]:
    if maximum_shots is not None and maximum_shots <= 0:
        raise ValueError("maximum_shots must be positive")
    payload = cast(Any, json.loads(labels_path.read_text(encoding="utf-8")))
    records = payload.get("attempts") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Shot labels must be a JSON list or an object with an attempts list")
    requested = set(shot_ids)
    labels: list[_ShotLabel] = []
    for index, raw_record in enumerate(cast(list[object], records)):
        if not isinstance(raw_record, dict):
            raise ValueError(f"Shot label {index} must be an object")
        record = cast(dict[str, object], raw_record)
        attempt_id = record.get("attempt_id", f"shot-{index + 1:03d}")
        release_seconds = record.get("release_seconds")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError(f"Shot label {index} has an invalid attempt_id")
        if isinstance(release_seconds, bool) or not isinstance(release_seconds, (int, float)):
            raise ValueError(f"Shot label {attempt_id} has an invalid release_seconds")
        if float(release_seconds) < 0:
            raise ValueError(f"Shot label {attempt_id} release_seconds cannot be negative")
        if requested and attempt_id not in requested:
            continue
        labels.append(_ShotLabel(attempt_id, float(release_seconds)))
    missing = requested - {label.attempt_id for label in labels}
    if missing:
        raise ValueError(f"Unknown shot IDs: {', '.join(sorted(missing))}")
    labels.sort(key=lambda item: (item.release_seconds, item.attempt_id))
    if maximum_shots is not None:
        labels = labels[:maximum_shots]
    if not labels:
        raise ValueError("No shot labels were selected")
    return tuple(labels)


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
    parser.add_argument("--shot-labels", type=Path)
    parser.add_argument("--shot-id", action="append", default=[])
    parser.add_argument("--maximum-shots", type=int)
    parser.add_argument("--window-before-seconds", type=float, default=0.8)
    parser.add_argument("--window-after-seconds", type=float, default=1.0)
    parser.add_argument("--release-window-seconds", type=float, default=0.5)
    parser.add_argument("--seed-confidence-threshold", type=float, default=0.5)
    parser.add_argument("--continuation-confidence-threshold", type=float, default=0.325)
    parser.add_argument("--continuation-max-area-ratio", type=float, default=4.0)
    parser.add_argument("--association-distance-fraction", type=float, default=0.12)
    parser.add_argument("--temporal-max-gap-frames", type=int, default=5)
    parser.add_argument("--temporal-max-gap-seconds", type=float, default=0.6)
    parser.add_argument("--temporal-box-expansion-fraction", type=float, default=0.35)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.video.exists():
        print(json.dumps({"status": "skipped", "reason": f"Video does not exist: {args.video}"}, indent=2))
        return 0
    model_options: JsonObject = {
        "seed_confidence_threshold": args.seed_confidence_threshold,
        "continuation_confidence_threshold": args.continuation_confidence_threshold,
        "continuation_max_area_ratio": args.continuation_max_area_ratio,
        "association_distance_fraction": args.association_distance_fraction,
        "temporal_max_gap_frames": args.temporal_max_gap_frames,
        "temporal_max_gap_seconds": args.temporal_max_gap_seconds,
        "temporal_box_expansion_fraction": args.temporal_box_expansion_fraction,
    }
    if args.shot_labels is not None:
        if args.backend != "mlx-sam3":
            parser.error("--shot-labels currently evaluates the mlx-sam3 adapter only")
        report = evaluate_labeled_windows(
            args.video,
            args.shot_labels,
            sampling_fps=args.sampling_fps,
            window_before_seconds=args.window_before_seconds,
            window_after_seconds=args.window_after_seconds,
            release_window_seconds=args.release_window_seconds,
            shot_ids=args.shot_id,
            maximum_shots=args.maximum_shots,
            model_path=args.model_path,
            model_options=model_options,
        )
    else:
        report = evaluate(
            args.video,
            maximum_seconds=args.maximum_seconds,
            sampling_fps=args.sampling_fps,
            backend_name=args.backend,
            model_path=args.model_path,
            model_options=model_options if args.backend == "mlx-sam3" else None,
        )
    payload = json.dumps(report, indent=2, sort_keys=True)
    print(payload)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
