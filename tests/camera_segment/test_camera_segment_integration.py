"""Generated-video integration tests for the camera segment service."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from shotsight2.adapters.ffmpeg import FFmpegAdapter
from shotsight2.adapters.opencv import OpenCVFrameSource
from shotsight2.domain.camera_segments import (
    CameraSegmentConfig,
    CameraSegmentTimeline,
    ManualBoundary,
    StabilityStatus,
)
from shotsight2.services.camera_segment_diagnostics import (
    evaluate_boundaries,
    timeline_diagnostic,
    write_timeline_diagnostic,
)
from shotsight2.services.camera_segments import CameraSegmentService

VideoFactory = Callable[[str, float], Path]


class RecordingRepository:
    """Small repository spy proving the service publishes one complete timeline."""

    def __init__(self) -> None:
        self.saved: tuple[UUID, CameraSegmentTimeline] | None = None

    def replace_for_run(self, analysis_run_id: UUID, timeline: CameraSegmentTimeline) -> None:
        self.saved = (analysis_run_id, timeline)


def _service(repository: RecordingRepository | None = None) -> CameraSegmentService:
    return CameraSegmentService(
        FFmpegAdapter(),
        OpenCVFrameSource(),
        repository,
        CameraSegmentConfig(
            sample_interval_seconds=0.2,
            analysis_width=160,
            motion_threshold=0.009,
            image_change_threshold=0.075,
            scene_change_threshold=0.28,
            noisy_range_max_seconds=0.2,
            transition_padding_seconds=0.2,
            minimum_stable_duration_seconds=1.0,
            representative_edge_margin_seconds=0.3,
        ),
    )


def test_fixed_camera_produces_one_deterministic_stable_segment(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Local object motion does not split a fixed camera viewpoint."""

    source = video_factory("fixed", 6.0)
    run_id = uuid4()
    repository = RecordingRepository()

    first = _service(repository).detect(source, run_id, tmp_path / "representatives")
    second = _service().detect(source, run_id, tmp_path / "representatives-second")

    assert len(first.stable_segments) == 1
    assert first.stable_segments[0].start_seconds == pytest.approx(0.0)
    assert first.stable_segments[0].end_seconds == pytest.approx(6.0, abs=0.11)
    assert first.stable_segments[0].representative_frame.exists()
    assert first.stable_segments[0].id == second.stable_segments[0].id
    assert first.ranges == second.ranges
    assert repository.saved == (run_id, first)


def test_setup_movement_is_skipped_before_stable_viewpoint(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Initial camera setup motion is excluded from downstream processing."""

    timeline = _service().detect(
        video_factory("setup", 6.0),
        uuid4(),
        tmp_path / "representatives",
    )

    assert timeline.ranges[0].status is StabilityStatus.UNSTABLE
    assert timeline.stable_segments
    assert timeline.stable_segments[0].start_seconds >= 1.6
    assert not timeline.should_process(0.5)
    assert timeline.should_process(4.0)


def test_angle_change_creates_independent_tracking_and_calibration_scopes(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """A new viewpoint cannot inherit calibration or a continuous track."""

    timeline = _service().detect(
        video_factory("angle", 7.0),
        uuid4(),
        tmp_path / "representatives",
    )

    assert len(timeline.stable_segments) == 2
    first, second = timeline.stable_segments
    assert first.end_seconds <= second.start_seconds
    assert first.calibration_scope_id != second.calibration_scope_id
    assert first.tracking_scope_id != second.tracking_scope_id
    assert any(
        timeline_range.status is not StabilityStatus.STABLE
        for timeline_range in timeline.ranges
        if first.end_seconds <= timeline_range.start_seconds <= second.start_seconds
    )


def test_repeated_camera_bumps_create_multiple_skip_ranges(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Repeated temporary camera displacement remains visible to downstream stages."""

    timeline = _service().detect(
        video_factory("bumps", 7.0),
        uuid4(),
        tmp_path / "representatives",
    )

    unstable = [
        timeline_range for timeline_range in timeline.ranges if timeline_range.status is StabilityStatus.UNSTABLE
    ]
    assert len(unstable) >= 2
    assert not timeline.should_process(2.4)
    assert not timeline.should_process(4.9)


def test_hard_cut_boundary_matches_manual_label_and_writes_diagnostic(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Detected boundaries can be benchmarked and inspected on the source timeline."""

    timeline = _service().detect(
        video_factory("hard-cut", 7.0),
        uuid4(),
        tmp_path / "representatives",
    )
    evaluation = evaluate_boundaries(
        timeline,
        (ManualBoundary(3.0, "viewpoint cut"),),
        tolerance_seconds=0.6,
    )
    destination = write_timeline_diagnostic(
        tmp_path / "diagnostics" / "timeline.json",
        timeline,
        evaluation,
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert evaluation.precision == 1.0
    assert evaluation.recall == 1.0
    assert evaluation.mean_absolute_error_seconds is not None
    assert evaluation.mean_absolute_error_seconds <= 0.6
    assert payload["ranges"]
    assert payload["features"]
    assert payload["skip_ranges"]
    assert payload["boundary_evaluation"]["recall"] == 1.0


def test_short_video_has_no_stable_segment(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Footage below minimum stable duration is entirely marked to skip."""

    timeline = _service().detect(
        video_factory("short", 0.7),
        uuid4(),
        tmp_path / "representatives",
    )

    assert timeline.stable_segments == ()
    assert all(timeline_range.status is not StabilityStatus.STABLE for timeline_range in timeline.ranges)


def test_boundary_evaluation_reports_misses_extras_and_invalid_tolerance(
    video_factory: VideoFactory,
    tmp_path: Path,
) -> None:
    """Diagnostics retain unmatched labels and detections for honest benchmarks."""

    timeline = _service().detect(
        video_factory("hard-cut", 7.0),
        uuid4(),
        tmp_path / "representatives",
    )
    evaluation = evaluate_boundaries(
        timeline,
        (ManualBoundary(1.0),),
        tolerance_seconds=0.1,
    )

    assert evaluation.precision == 0.0
    assert evaluation.recall == 0.0
    assert evaluation.missed_expected_seconds == (1.0,)
    assert evaluation.extra_detected_seconds
    assert timeline_diagnostic(timeline)["detected_boundaries_seconds"]
    with pytest.raises(ValueError):
        evaluate_boundaries(timeline, (), tolerance_seconds=-1)
