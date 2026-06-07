"""Unit tests for camera segmentation domain behavior and range cleanup."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from shotsight2.domain.camera_segments import (
    CameraSegmentConfig,
    CameraSegmentTimeline,
    ClassifiedInterval,
    StabilityRange,
    StabilityStatus,
)
from shotsight2.ports.camera_segments import SampledFrame
from shotsight2.services.camera_segments import (
    build_stability_ranges,
    enforce_minimum_stable_duration,
    extract_motion_features,
    merge_short_noisy_intervals,
)


def _interval(start: float, end: float, status: StabilityStatus) -> ClassifiedInterval:
    return ClassifiedInterval(start, end, status, confidence=0.8, motion=0.01)


def test_configuration_rejects_invalid_thresholds() -> None:
    """Invalid sampling and threshold policies fail at construction."""

    with pytest.raises(ValueError):
        CameraSegmentConfig(sample_interval_seconds=0)
    with pytest.raises(ValueError):
        CameraSegmentConfig(image_change_threshold=0.5, scene_change_threshold=0.3)


def test_fixed_frames_have_negligible_motion() -> None:
    """Identical low-resolution frames produce stable motion evidence."""

    pixels = np.full((48, 64), 120, dtype=np.uint8)
    features = extract_motion_features(
        (
            SampledFrame(0.0, pixels),
            SampledFrame(0.25, pixels.copy()),
        )
    )

    assert features[0].global_motion == pytest.approx(0.0)
    assert features[0].image_change == pytest.approx(0.0)
    assert features[0].scene_change == pytest.approx(0.0)


def test_motion_features_require_increasing_timestamps_and_matching_shapes() -> None:
    """Malformed frame streams are rejected instead of silently misclassified."""

    pixels = np.zeros((20, 20), dtype=np.uint8)
    with pytest.raises(ValueError, match="strictly increasing"):
        extract_motion_features((SampledFrame(1.0, pixels), SampledFrame(1.0, pixels)))
    with pytest.raises(ValueError, match="matching dimensions"):
        extract_motion_features(
            (
                SampledFrame(0.0, pixels),
                SampledFrame(1.0, np.zeros((10, 10), dtype=np.uint8)),
            )
        )


def test_short_noise_island_merges_into_surrounding_status() -> None:
    """One brief contradictory classification does not split a viewpoint."""

    cleaned = merge_short_noisy_intervals(
        (
            _interval(0.0, 1.0, StabilityStatus.STABLE),
            _interval(1.0, 1.25, StabilityStatus.UNSTABLE),
            _interval(1.25, 2.0, StabilityStatus.STABLE),
        ),
        maximum_duration_seconds=0.25,
    )

    assert {item.status for item in cleaned} == {StabilityStatus.STABLE}


def test_transition_is_not_erased_as_short_noise() -> None:
    """Hard cuts remain explicit even when shorter than the cleanup window."""

    cleaned = merge_short_noisy_intervals(
        (
            _interval(0.0, 1.0, StabilityStatus.STABLE),
            _interval(1.0, 1.25, StabilityStatus.TRANSITION),
            _interval(1.25, 2.0, StabilityStatus.STABLE),
        ),
        maximum_duration_seconds=0.5,
    )

    assert cleaned[1].status is StabilityStatus.TRANSITION


def test_minimum_duration_reclassifies_short_stable_island() -> None:
    """Stable ranges too short for useful tracking become explicit skip ranges."""

    enforced = enforce_minimum_stable_duration(
        (
            _interval(0.0, 0.75, StabilityStatus.STABLE),
            _interval(0.75, 1.0, StabilityStatus.TRANSITION),
        ),
        minimum_duration_seconds=1.0,
    )

    assert enforced[0].status is StabilityStatus.UNSTABLE


def test_empty_and_grouped_ranges_cover_the_complete_source() -> None:
    """Timeline output remains gap-free for short and normally sampled videos."""

    assert build_stability_ranges((), duration_seconds=0.5) == (
        StabilityRange(0.0, 0.5, StabilityStatus.UNSTABLE, 0.0),
    )
    ranges = build_stability_ranges(
        (
            _interval(0.1, 0.5, StabilityStatus.STABLE),
            _interval(0.5, 0.75, StabilityStatus.UNSTABLE),
        ),
        duration_seconds=1.0,
    )

    assert ranges[0].start_seconds == 0.0
    assert ranges[-1].end_seconds == 1.0


def test_timeline_exposes_downstream_skip_decision() -> None:
    """Tracking and shot stages can reject unstable timestamps directly."""

    timeline = CameraSegmentTimeline(
        analysis_run_id=uuid4(),
        source=Path("proxy.mp4"),
        duration_seconds=2.0,
        ranges=(
            StabilityRange(0.0, 1.0, StabilityStatus.UNSTABLE, 0.8),
            StabilityRange(1.0, 2.0, StabilityStatus.STABLE, 0.9),
        ),
        stable_segments=(),
        features=(),
    )

    assert not timeline.should_process(0.5)
    assert timeline.should_process(1.5)
    with pytest.raises(ValueError):
        timeline.status_at(2.1)
