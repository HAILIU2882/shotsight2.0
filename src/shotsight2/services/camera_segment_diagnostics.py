"""Serializable camera-boundary diagnostics and benchmark evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shotsight2.domain.camera_segments import (
    BoundaryEvaluation,
    BoundaryMatch,
    CameraSegmentTimeline,
    ManualBoundary,
    StabilityStatus,
)


def detected_boundaries(timeline: CameraSegmentTimeline) -> tuple[float, ...]:
    """Return stable-viewpoint starts after the first source range."""

    return tuple(segment.start_seconds for segment in timeline.stable_segments if segment.start_seconds > 0)


def evaluate_boundaries(
    timeline: CameraSegmentTimeline,
    expected: tuple[ManualBoundary, ...],
    *,
    tolerance_seconds: float,
) -> BoundaryEvaluation:
    """Greedily match detections to nearest manual labels within tolerance."""

    if tolerance_seconds < 0:
        raise ValueError("Boundary tolerance cannot be negative")
    unmatched_detected = list(detected_boundaries(timeline))
    matches: list[BoundaryMatch] = []
    missed: list[float] = []
    for boundary in sorted(expected, key=lambda item: item.timestamp_seconds):
        candidates = [
            detected
            for detected in unmatched_detected
            if abs(detected - boundary.timestamp_seconds) <= tolerance_seconds
        ]
        if not candidates:
            missed.append(boundary.timestamp_seconds)
            continue
        selected = min(candidates, key=lambda value: (abs(value - boundary.timestamp_seconds), value))
        unmatched_detected.remove(selected)
        matches.append(
            BoundaryMatch(
                detected_seconds=selected,
                expected_seconds=boundary.timestamp_seconds,
                error_seconds=abs(selected - boundary.timestamp_seconds),
            )
        )
    return BoundaryEvaluation(
        tolerance_seconds=tolerance_seconds,
        matches=tuple(matches),
        missed_expected_seconds=tuple(missed),
        extra_detected_seconds=tuple(unmatched_detected),
    )


def timeline_diagnostic(
    timeline: CameraSegmentTimeline,
    evaluation: BoundaryEvaluation | None = None,
) -> dict[str, Any]:
    """Build a JSON-compatible timeline diagnostic for benchmark reports."""

    payload: dict[str, Any] = {
        "analysis_run_id": str(timeline.analysis_run_id),
        "source": str(timeline.source),
        "duration_seconds": timeline.duration_seconds,
        "ranges": [
            {
                **asdict(timeline_range),
                "status": timeline_range.status.value,
            }
            for timeline_range in timeline.ranges
        ],
        "stable_segments": [
            {
                "id": str(segment.id),
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "confidence": segment.confidence,
                "representative_frame": str(segment.representative_frame),
                "representative_timestamp_seconds": segment.representative_timestamp_seconds,
                "calibration_scope_id": str(segment.calibration_scope_id),
                "tracking_scope_id": str(segment.tracking_scope_id),
            }
            for segment in timeline.stable_segments
        ],
        "features": [asdict(feature) for feature in timeline.features],
        "skip_ranges": [
            asdict(timeline_range) | {"status": timeline_range.status.value}
            for timeline_range in timeline.ranges
            if timeline_range.status is not StabilityStatus.STABLE
        ],
        "detected_boundaries_seconds": list(detected_boundaries(timeline)),
    }
    if evaluation is not None:
        payload["boundary_evaluation"] = {
            "tolerance_seconds": evaluation.tolerance_seconds,
            "precision": evaluation.precision,
            "recall": evaluation.recall,
            "mean_absolute_error_seconds": evaluation.mean_absolute_error_seconds,
            "matches": [asdict(match) for match in evaluation.matches],
            "missed_expected_seconds": list(evaluation.missed_expected_seconds),
            "extra_detected_seconds": list(evaluation.extra_detected_seconds),
        }
    return payload


def write_timeline_diagnostic(
    destination: Path,
    timeline: CameraSegmentTimeline,
    evaluation: BoundaryEvaluation | None = None,
) -> Path:
    """Write a deterministic, human-readable JSON timeline diagnostic."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(timeline_diagnostic(timeline, evaluation), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
