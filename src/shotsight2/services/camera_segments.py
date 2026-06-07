"""Camera motion analysis and stable-viewpoint segmentation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import cv2
import numpy as np

from shotsight2.domain import CameraSegment as PersistenceCameraSegment
from shotsight2.domain.camera_segments import (
    CameraSegment,
    CameraSegmentConfig,
    CameraSegmentTimeline,
    ClassifiedInterval,
    MotionFeature,
    StabilityRange,
    StabilityStatus,
)
from shotsight2.domain.media import FrameExtractionRequest
from shotsight2.ports.camera_segments import (
    CameraFrameSource,
    GrayFrame,
    SampledFrame,
)
from shotsight2.ports.media import MediaTool
from shotsight2.ports.repositories import CameraSegmentRepository


class CameraSegmentService:
    """Detect camera changes and publish stable, independently scoped ranges."""

    def __init__(
        self,
        media_tool: MediaTool,
        frame_source: CameraFrameSource,
        repository: CameraSegmentRepository | None = None,
        config: CameraSegmentConfig | None = None,
    ) -> None:
        self._media_tool = media_tool
        self._frame_source = frame_source
        self._repository = repository
        self._config = config or CameraSegmentConfig()

    def detect(
        self,
        source: Path,
        analysis_run_id: str,
        representative_directory: Path,
    ) -> CameraSegmentTimeline:
        """Detect and optionally persist a complete camera-stability timeline."""

        metadata = self._media_tool.probe(source)
        frames = tuple(
            self._frame_source.sample(
                source,
                duration_seconds=metadata.duration_seconds,
                interval_seconds=self._config.sample_interval_seconds,
                analysis_width=self._config.analysis_width,
            )
        )
        features = extract_motion_features(frames)
        raw_intervals = classify_features(features, self._config)
        padded_intervals = apply_transition_padding(raw_intervals, self._config.transition_padding_seconds)
        cleaned_intervals = merge_short_noisy_intervals(
            padded_intervals,
            self._config.noisy_range_max_seconds,
        )
        stable_enforced = enforce_minimum_stable_duration(
            cleaned_intervals,
            self._config.minimum_stable_duration_seconds,
        )
        ranges = build_stability_ranges(
            stable_enforced,
            duration_seconds=metadata.duration_seconds,
        )
        segments = self._create_stable_segments(
            analysis_run_id=analysis_run_id,
            source=source,
            representative_directory=representative_directory,
            ranges=ranges,
            features=features,
        )
        timeline = CameraSegmentTimeline(
            analysis_run_id=analysis_run_id,
            source=source,
            duration_seconds=metadata.duration_seconds,
            ranges=ranges,
            stable_segments=segments,
            features=features,
        )
        if self._repository is not None:
            self._repository.replace_for_run(
                analysis_run_id,
                to_persistence_segments(timeline),
            )
        return timeline

    def _create_stable_segments(
        self,
        *,
        analysis_run_id: str,
        source: Path,
        representative_directory: Path,
        ranges: Sequence[StabilityRange],
        features: Sequence[MotionFeature],
    ) -> tuple[CameraSegment, ...]:
        segments: list[CameraSegment] = []
        for index, timeline_range in enumerate(ranges):
            if timeline_range.status is not StabilityStatus.STABLE:
                continue
            representative_timestamp = choose_representative_timestamp(
                timeline_range,
                features,
                self._config.representative_edge_margin_seconds,
            )
            segment_id = _scoped_id(
                analysis_run_id,
                f"camera:{index}:{timeline_range.start_seconds:.6f}:{timeline_range.end_seconds:.6f}",
            )
            destination = representative_directory / f"{segment_id}.jpg"
            extracted = self._media_tool.extract_frame(
                FrameExtractionRequest(
                    source=source,
                    destination=destination,
                    timestamp_seconds=representative_timestamp,
                )
            )
            segments.append(
                CameraSegment(
                    id=segment_id,
                    analysis_run_id=analysis_run_id,
                    start_seconds=timeline_range.start_seconds,
                    end_seconds=timeline_range.end_seconds,
                    confidence=timeline_range.confidence,
                    representative_frame=extracted.path,
                    representative_timestamp_seconds=representative_timestamp,
                    calibration_scope_id=_scoped_id(segment_id, "calibration"),
                    tracking_scope_id=_scoped_id(segment_id, "tracking"),
                )
            )
        return tuple(segments)


def extract_motion_features(frames: Sequence[SampledFrame]) -> tuple[MotionFeature, ...]:
    """Extract translation, residual image change, and scene-change evidence."""

    features: list[MotionFeature] = []
    for previous, current in zip(frames, frames[1:], strict=False):
        if current.timestamp_seconds <= previous.timestamp_seconds:
            raise ValueError("Sampled frame timestamps must be strictly increasing")
        global_motion, aligned_change, phase_confidence = _global_motion(
            previous.pixels,
            current.pixels,
        )
        scene_change = _scene_change(previous.pixels, current.pixels)
        confidence = min(1.0, max(0.0, phase_confidence))
        features.append(
            MotionFeature(
                start_seconds=previous.timestamp_seconds,
                end_seconds=current.timestamp_seconds,
                global_motion=global_motion,
                image_change=aligned_change,
                scene_change=scene_change,
                confidence=confidence,
            )
        )
    return tuple(features)


def classify_features(
    features: Iterable[MotionFeature],
    config: CameraSegmentConfig,
) -> tuple[ClassifiedInterval, ...]:
    """Classify motion evidence into stable, unstable, and transition intervals."""

    intervals: list[ClassifiedInterval] = []
    for feature in features:
        if feature.scene_change >= config.scene_change_threshold:
            status = StabilityStatus.TRANSITION
            margin = feature.scene_change / config.scene_change_threshold
        elif feature.global_motion >= config.motion_threshold or feature.image_change >= config.image_change_threshold:
            status = StabilityStatus.UNSTABLE
            margin = max(
                feature.global_motion / config.motion_threshold,
                feature.image_change / config.image_change_threshold,
            )
        else:
            status = StabilityStatus.STABLE
            margin = 1.0 - max(
                feature.global_motion / config.motion_threshold,
                feature.image_change / config.image_change_threshold,
                feature.scene_change / config.scene_change_threshold,
            )
        intervals.append(
            ClassifiedInterval(
                start_seconds=feature.start_seconds,
                end_seconds=feature.end_seconds,
                status=status,
                confidence=min(1.0, max(0.0, margin)),
                motion=max(feature.global_motion, feature.image_change),
            )
        )
    return tuple(intervals)


def apply_transition_padding(
    intervals: Sequence[ClassifiedInterval],
    padding_seconds: float,
) -> tuple[ClassifiedInterval, ...]:
    """Mark intervals neighboring hard cuts as unstable transition buffers."""

    if padding_seconds <= 0:
        return tuple(intervals)
    transition_ranges = tuple(interval for interval in intervals if interval.status is StabilityStatus.TRANSITION)
    padded: list[ClassifiedInterval] = []
    for interval in intervals:
        if interval.status is not StabilityStatus.STABLE:
            padded.append(interval)
            continue
        near_transition = any(
            interval.end_seconds > transition.start_seconds - padding_seconds
            and interval.start_seconds < transition.end_seconds + padding_seconds
            for transition in transition_ranges
        )
        if near_transition:
            padded.append(
                ClassifiedInterval(
                    start_seconds=interval.start_seconds,
                    end_seconds=interval.end_seconds,
                    status=StabilityStatus.UNSTABLE,
                    confidence=interval.confidence,
                    motion=interval.motion,
                )
            )
        else:
            padded.append(interval)
    return tuple(padded)


def merge_short_noisy_intervals(
    intervals: Sequence[ClassifiedInterval],
    maximum_duration_seconds: float,
) -> tuple[ClassifiedInterval, ...]:
    """Replace short classification islands enclosed by one other status."""

    if maximum_duration_seconds <= 0 or len(intervals) < 3:
        return tuple(intervals)
    result = list(intervals)
    changed = True
    while changed:
        changed = False
        groups = _interval_groups(result)
        for group_index, (start, end) in enumerate(groups):
            if group_index == 0 or group_index == len(groups) - 1:
                continue
            duration = result[end - 1].end_seconds - result[start].start_seconds
            previous_status = result[groups[group_index - 1][0]].status
            next_status = result[groups[group_index + 1][0]].status
            current_status = result[start].status
            if (
                duration <= maximum_duration_seconds
                and previous_status is next_status
                and current_status is not StabilityStatus.TRANSITION
            ):
                for item_index in range(start, end):
                    item = result[item_index]
                    result[item_index] = ClassifiedInterval(
                        start_seconds=item.start_seconds,
                        end_seconds=item.end_seconds,
                        status=previous_status,
                        confidence=item.confidence,
                        motion=item.motion,
                    )
                changed = True
                break
    return tuple(result)


def enforce_minimum_stable_duration(
    intervals: Sequence[ClassifiedInterval],
    minimum_duration_seconds: float,
) -> tuple[ClassifiedInterval, ...]:
    """Reclassify stable islands shorter than the configured useful duration."""

    result = list(intervals)
    for start, end in _interval_groups(result):
        if result[start].status is not StabilityStatus.STABLE:
            continue
        duration = result[end - 1].end_seconds - result[start].start_seconds
        if duration >= minimum_duration_seconds:
            continue
        for index in range(start, end):
            interval = result[index]
            result[index] = ClassifiedInterval(
                start_seconds=interval.start_seconds,
                end_seconds=interval.end_seconds,
                status=StabilityStatus.UNSTABLE,
                confidence=interval.confidence,
                motion=interval.motion,
            )
    return tuple(result)


def build_stability_ranges(
    intervals: Sequence[ClassifiedInterval],
    *,
    duration_seconds: float,
) -> tuple[StabilityRange, ...]:
    """Collapse classified samples into a gap-free source timeline."""

    if duration_seconds <= 0:
        raise ValueError("Source duration must be positive")
    if not intervals:
        return (
            StabilityRange(
                start_seconds=0.0,
                end_seconds=duration_seconds,
                status=StabilityStatus.UNSTABLE,
                confidence=0.0,
            ),
        )
    ranges: list[StabilityRange] = []
    for start, end in _interval_groups(intervals):
        grouped = intervals[start:end]
        ranges.append(
            StabilityRange(
                start_seconds=grouped[0].start_seconds,
                end_seconds=grouped[-1].end_seconds,
                status=grouped[0].status,
                confidence=sum(item.confidence for item in grouped) / len(grouped),
            )
        )
    first = ranges[0]
    ranges[0] = StabilityRange(0.0, first.end_seconds, first.status, first.confidence)
    last = ranges[-1]
    ranges[-1] = StabilityRange(
        last.start_seconds,
        duration_seconds,
        last.status,
        last.confidence,
    )
    return tuple(ranges)


def choose_representative_timestamp(
    stable_range: StabilityRange,
    features: Sequence[MotionFeature],
    edge_margin_seconds: float,
) -> float:
    """Choose the least-changing sample near the middle of a stable range."""

    usable_margin = min(edge_margin_seconds, stable_range.duration_seconds / 4)
    earliest = stable_range.start_seconds + usable_margin
    latest = stable_range.end_seconds - usable_margin
    midpoint = (stable_range.start_seconds + stable_range.end_seconds) / 2
    candidates = [
        feature for feature in features if earliest <= (feature.start_seconds + feature.end_seconds) / 2 <= latest
    ]
    if not candidates:
        return midpoint
    selected = min(
        candidates,
        key=lambda feature: (
            feature.global_motion + feature.image_change + feature.scene_change,
            abs(((feature.start_seconds + feature.end_seconds) / 2) - midpoint),
            feature.start_seconds,
        ),
    )
    return (selected.start_seconds + selected.end_seconds) / 2


def _global_motion(previous: GrayFrame, current: GrayFrame) -> tuple[float, float, float]:
    if previous.shape != current.shape:
        raise ValueError("Sampled frames must have matching dimensions")
    direct_change = float(np.mean(cv2.absdiff(previous, current)) / 255.0)
    if direct_change <= 1e-9:
        return 0.0, 0.0, 1.0
    previous_float = previous.astype(np.float32)
    current_float = current.astype(np.float32)
    (shift_x, shift_y), response = cv2.phaseCorrelate(previous_float, current_float)
    diagonal = float(np.hypot(previous.shape[1], previous.shape[0]))
    normalized_motion = float(np.hypot(shift_x, shift_y) / diagonal)
    transform = np.array([[1.0, 0.0, -shift_x], [0.0, 1.0, -shift_y]], dtype=np.float32)
    aligned = cv2.warpAffine(
        current,
        transform,
        (previous.shape[1], previous.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )
    residual = float(np.mean(cv2.absdiff(previous, aligned)) / 255.0)
    return normalized_motion, residual, float(response)


def _scene_change(previous: GrayFrame, current: GrayFrame) -> float:
    histogram_previous = cv2.calcHist([previous], [0], None, [32], [0, 256])
    histogram_current = cv2.calcHist([current], [0], None, [32], [0, 256])
    cv2.normalize(histogram_previous, histogram_previous)
    cv2.normalize(histogram_current, histogram_current)
    histogram_distance = float(cv2.compareHist(histogram_previous, histogram_current, cv2.HISTCMP_BHATTACHARYYA))
    pixel_change = float(np.mean(cv2.absdiff(previous, current)) / 255.0)
    return max(histogram_distance, pixel_change)


def _interval_groups(intervals: Sequence[ClassifiedInterval]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    groups: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(intervals)):
        if intervals[index].status is intervals[start].status:
            continue
        groups.append((start, index))
        start = index
    groups.append((start, len(intervals)))
    return groups


def to_persistence_segments(
    timeline: CameraSegmentTimeline,
) -> tuple[PersistenceCameraSegment, ...]:
    """Convert the rich timeline into canonical repository records."""

    stable_by_range = {(segment.start_seconds, segment.end_seconds): segment for segment in timeline.stable_segments}
    records: list[PersistenceCameraSegment] = []
    for index, timeline_range in enumerate(timeline.ranges):
        stable_segment = stable_by_range.get((timeline_range.start_seconds, timeline_range.end_seconds))
        segment_id = (
            stable_segment.id
            if stable_segment is not None
            else _scoped_id(
                timeline.analysis_run_id,
                (
                    f"range:{index}:{timeline_range.status.value}:"
                    f"{timeline_range.start_seconds:.6f}:{timeline_range.end_seconds:.6f}"
                ),
            )
        )
        records.append(
            PersistenceCameraSegment(
                id=segment_id,
                analysis_run_id=timeline.analysis_run_id,
                start_seconds=timeline_range.start_seconds,
                end_seconds=timeline_range.end_seconds,
                stability_status=timeline_range.status.value.upper(),
                confidence=timeline_range.confidence,
                representative_artifact_id=(
                    str(stable_segment.representative_frame) if stable_segment is not None else None
                ),
            )
        )
    return tuple(records)


def _scoped_id(namespace: str, name: str) -> str:
    scope = uuid5(NAMESPACE_URL, namespace)
    return str(uuid5(scope, name))
