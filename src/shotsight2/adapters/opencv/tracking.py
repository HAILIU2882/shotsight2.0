"""Runnable OpenCV fallback tracking and frame decoding."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import uuid4

import cv2
import numpy as np
import numpy.typing as npt

from shotsight2.domain.tracking import (
    BoundingBox,
    CameraSegmentInput,
    FrameBatch,
    ImagePoint,
    ModelConfig,
    ObservationProvenance,
    PromptSource,
    TrackedObjectClass,
    TrackingBatchResult,
    TrackingFrame,
    TrackingMetrics,
    TrackingPrompt,
    TrackingSession,
    TrackingSummary,
    TrackObservation,
    VisibilityState,
)
from shotsight2.domain.tracking_backends import BackendCapabilities, DeviceType

ColorFrame = npt.NDArray[np.uint8]
GrayFrame = npt.NDArray[np.uint8]


class OpenCVTrackingError(RuntimeError):
    """Raised when fallback decoding or tracking cannot proceed."""


class OpenCVTrackingFrameSource:
    """Decode a stable segment into bounded color-frame batches."""

    def __init__(
        self,
        source: Path,
        *,
        batch_size: int = 16,
        sampling_fps: float | None = None,
    ) -> None:
        if batch_size <= 0 or (sampling_fps is not None and sampling_fps <= 0):
            raise ValueError("Batch size and sampling frame rate must be positive")
        self._source = source
        self._batch_size = batch_size
        self._sampling_fps = sampling_fps

    def batches(self, segment: CameraSegmentInput) -> Iterable[FrameBatch]:
        """Yield ascending source frames within the segment time range."""

        capture = cv2.VideoCapture(str(self._source))
        if not capture.isOpened():
            raise OpenCVTrackingError(f"Unable to open tracking source: {self._source}")
        capture.set(cv2.CAP_PROP_POS_MSEC, segment.start_seconds * 1000)
        frames: list[TrackingFrame] = []
        next_timestamp = segment.start_seconds
        try:
            while True:
                decoded, pixels = capture.read()
                if not decoded or pixels is None:
                    break
                timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                if timestamp > segment.end_seconds:
                    break
                if self._sampling_fps is not None and timestamp + 1e-6 < next_timestamp:
                    continue
                if self._sampling_fps is not None:
                    next_timestamp = timestamp + 1 / self._sampling_fps
                frame_index = max(0, round(timestamp * segment.fps))
                frames.append(TrackingFrame(frame_index, timestamp, pixels))
                if len(frames) == self._batch_size:
                    yield FrameBatch(tuple(frames))
                    frames.clear()
            if frames:
                yield FrameBatch(tuple(frames))
        finally:
            capture.release()


@dataclass(slots=True)
class _TemplateTrack:
    object_class: TrackedObjectClass
    local_track_id: str
    box: BoundingBox
    template: GrayFrame
    prompt_id: str | None
    reinitialized: bool


@dataclass(slots=True)
class _SessionState:
    segment: CameraSegmentInput
    prompts: list[TrackingPrompt]
    tracks: dict[str, _TemplateTrack] = field(default_factory=dict)
    observations: int = 0
    observed_ball_frames: set[int] = field(default_factory=set)
    reinitializations: int = 0


class OpenCVTrackingBackend:
    """CPU fallback using color proposals and template propagation."""

    _CAPABILITIES = BackendCapabilities(
        text_prompts=False,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=False,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=True,
        mask_output=False,
        supported_devices=(DeviceType.CPU,),
        maximum_recommended_resolution=(960, 540),
    )

    def __init__(self) -> None:
        self._loaded = False
        self._sessions: dict[str, _SessionState] = {}
        self._version = str(getattr(cv2, "__version__", "unknown"))

    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def load(self, model_config: ModelConfig) -> None:
        """Initialize the package-free heuristic backend."""

        del model_config
        self._loaded = True

    def start_segment(
        self,
        segment: CameraSegmentInput,
        prompts: Sequence[TrackingPrompt],
    ) -> TrackingSession:
        """Create a clean state container for one camera viewpoint."""

        if not self._loaded:
            raise OpenCVTrackingError("OpenCV backend must be loaded before use")
        if any(prompt.segment_id != segment.id for prompt in prompts):
            raise ValueError("Every prompt must belong to the started segment")
        session = TrackingSession(str(uuid4()), segment.id, "opencv-cpu")
        self._sessions[session.id] = _SessionState(segment, list(prompts))
        return session

    def process_batch(self, session: TrackingSession, frames: FrameBatch) -> TrackingBatchResult:
        """Track prompts and automatic basketball/rim proposals."""

        state = self._state(session)
        observations: list[TrackObservation] = []
        for frame in frames.frames:
            pixels = _color_frame(frame.pixels)
            gray = cast(GrayFrame, cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY))
            self._activate_user_prompts(state, frame, gray)
            observations.extend(self._propagate_tracks(state, session, frame, gray))
            tracked_classes = {item.object_class for item in observations if item.frame_index == frame.frame_index}
            if TrackedObjectClass.BASKETBALL not in tracked_classes:
                ball = _best_ball_candidate(pixels)
                if ball is not None:
                    observations.append(
                        self._observation(
                            state,
                            session,
                            frame,
                            TrackedObjectClass.BASKETBALL,
                            "ball-1",
                            ball,
                            0.58,
                        )
                    )
                    state.tracks["ball-1"] = _make_track(
                        gray,
                        TrackedObjectClass.BASKETBALL,
                        "ball-1",
                        ball,
                        None,
                        False,
                    )
            if TrackedObjectClass.RIM not in tracked_classes:
                rim = _best_rim_candidate(pixels)
                if rim is not None:
                    observations.append(
                        self._observation(
                            state,
                            session,
                            frame,
                            TrackedObjectClass.RIM,
                            "rim-1",
                            rim,
                            0.5,
                        )
                    )
            if (
                TrackedObjectClass.PLAYER not in tracked_classes
                and frame.frame_index % max(1, round(state.segment.fps / 2)) == 0
            ):
                for index, player in enumerate(self._player_candidates(pixels), start=1):
                    local_id = f"player-{index}"
                    observations.append(
                        self._observation(
                            state,
                            session,
                            frame,
                            TrackedObjectClass.PLAYER,
                            local_id,
                            player,
                            0.5,
                        )
                    )
                    state.tracks[local_id] = _make_track(
                        gray,
                        TrackedObjectClass.PLAYER,
                        local_id,
                        player,
                        None,
                        False,
                    )
            state.observations += sum(item.frame_index == frame.frame_index for item in observations)
            if any(
                item.frame_index == frame.frame_index and item.object_class is TrackedObjectClass.BASKETBALL
                for item in observations
            ):
                state.observed_ball_frames.add(frame.frame_index)
        return TrackingBatchResult(tuple(observations))

    def add_prompt(self, session: TrackingSession, prompt: TrackingPrompt) -> None:
        """Queue a prompt to activate at its timestamp."""

        state = self._state(session)
        if prompt.segment_id != state.segment.id:
            raise ValueError("Prompt belongs to a different segment")
        state.prompts.append(prompt)

    def close_segment(self, session: TrackingSession) -> TrackingSummary:
        """Close and discard every piece of segment state."""

        state = self._state(session)
        del self._sessions[session.id]
        expected = max(1, round((state.segment.end_seconds - state.segment.start_seconds) * state.segment.fps))
        return TrackingSummary(
            session.id,
            session.segment_id,
            session.backend_name,
            state.observations,
            TrackingMetrics(
                expected_frames=expected,
                observed_frames=len(state.observed_ball_frames),
                reinitializations=state.reinitializations,
                identity_switches=0,
                lost_events=0,
                occlusion_events=0,
            ),
        )

    def unload(self) -> None:
        """Release all state without importing any model package."""

        self._sessions.clear()
        self._loaded = False

    def _state(self, session: TrackingSession) -> _SessionState:
        try:
            return self._sessions[session.id]
        except KeyError as error:
            raise OpenCVTrackingError("Unknown or closed tracking session") from error

    def _activate_user_prompts(
        self,
        state: _SessionState,
        frame: TrackingFrame,
        gray: GrayFrame,
    ) -> None:
        remaining: list[TrackingPrompt] = []
        for prompt in state.prompts:
            if prompt.source is not PromptSource.USER or prompt.timestamp_seconds > frame.timestamp_seconds:
                remaining.append(prompt)
                continue
            box = prompt.box or _point_box(prompt.point, state.segment)
            if box is None:
                continue
            local_id = prompt.target_track_id or f"{prompt.object_class.value}-1"
            state.tracks[local_id] = _make_track(
                gray,
                prompt.object_class,
                local_id,
                box,
                prompt.id,
                True,
            )
            state.reinitializations += 1
        state.prompts = remaining

    def _propagate_tracks(
        self,
        state: _SessionState,
        session: TrackingSession,
        frame: TrackingFrame,
        gray: GrayFrame,
    ) -> list[TrackObservation]:
        observations: list[TrackObservation] = []
        for local_id, track in tuple(state.tracks.items()):
            matched = _match_template(gray, track)
            if matched is None:
                continue
            box, confidence = matched
            state.tracks[local_id] = _make_track(
                gray,
                track.object_class,
                local_id,
                box,
                track.prompt_id,
                False,
            )
            observations.append(
                self._observation(
                    state,
                    session,
                    frame,
                    track.object_class,
                    local_id,
                    box,
                    confidence,
                    prompt_id=track.prompt_id,
                    reinitialized=track.reinitialized,
                )
            )
        return observations

    def _observation(
        self,
        state: _SessionState,
        session: TrackingSession,
        frame: TrackingFrame,
        object_class: TrackedObjectClass,
        local_id: str,
        box: BoundingBox,
        confidence: float,
        *,
        prompt_id: str | None = None,
        reinitialized: bool = False,
    ) -> TrackObservation:
        return TrackObservation(
            id=f"{session.id}:{frame.frame_index}:{object_class.value}:{local_id}",
            segment_id=state.segment.id,
            frame_index=frame.frame_index,
            timestamp_seconds=frame.timestamp_seconds,
            object_class=object_class,
            local_track_id=local_id,
            bounding_box=box,
            centroid=box.centroid,
            confidence=max(0.0, min(1.0, confidence)),
            visibility=VisibilityState.VISIBLE,
            occluded=False,
            provenance=ObservationProvenance(
                backend_name="opencv-cpu",
                backend_version=self._version,
                model="opencv-heuristic",
                session_id=session.id,
                prompt_id=prompt_id,
                reinitialized=reinitialized,
            ),
        )

    def _player_candidates(self, frame: ColorFrame) -> tuple[BoundingBox, ...]:
        scale = min(1.0, 640 / frame.shape[1])
        resized = frame
        if scale < 1:
            resized = cast(
                ColorFrame,
                cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA),
            )
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        lower = np.array(35, dtype=np.uint8)
        upper = np.array(255, dtype=np.uint8)
        foreground = cv2.inRange(saturation, lower, upper)
        value_mask = cv2.inRange(
            value,
            np.array(25, dtype=np.uint8),
            np.array(245, dtype=np.uint8),
        )
        foreground = cv2.bitwise_and(foreground, value_mask)
        foreground = cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            np.ones((7, 5), dtype=np.uint8),
            iterations=2,
        )
        contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        inverse = 1 / scale
        frame_area = resized.shape[0] * resized.shape[1]
        candidates: list[BoundingBox] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            area = width * height
            aspect = height / max(1, width)
            if area < frame_area * 0.01 or area > frame_area * 0.45:
                continue
            if height < resized.shape[0] * 0.16 or not 0.8 <= aspect <= 4.5:
                continue
            candidates.append(
                BoundingBox(
                    float(x * inverse),
                    float(y * inverse),
                    float(width * inverse),
                    float(height * inverse),
                )
            )
        candidates.sort(key=lambda item: (-item.area, item.x, item.y))
        return tuple(sorted(candidates[:10], key=lambda item: (item.x, item.y)))


def _color_frame(value: object) -> ColorFrame:
    if not isinstance(value, np.ndarray) or value.ndim != 3:
        raise TypeError("OpenCV tracking frames must be color numpy arrays")
    return value


def _point_box(point: ImagePoint | None, segment: CameraSegmentInput) -> BoundingBox | None:
    if point is None:
        return None
    radius = max(4.0, min(segment.width, segment.height) * 0.015)
    return BoundingBox(
        max(0.0, point.x - radius),
        max(0.0, point.y - radius),
        min(radius * 2, segment.width - max(0.0, point.x - radius)),
        min(radius * 2, segment.height - max(0.0, point.y - radius)),
    )


def _make_track(
    gray: GrayFrame,
    object_class: TrackedObjectClass,
    local_id: str,
    box: BoundingBox,
    prompt_id: str | None,
    reinitialized: bool,
) -> _TemplateTrack:
    clipped = _clip_box(box, gray.shape[1], gray.shape[0])
    x, y, width, height = _integer_box(clipped)
    template = gray[y : y + height, x : x + width].copy()
    return _TemplateTrack(object_class, local_id, clipped, template, prompt_id, reinitialized)


def _match_template(gray: GrayFrame, track: _TemplateTrack) -> tuple[BoundingBox, float] | None:
    if track.template.size == 0:
        return None
    margin = max(track.box.width, track.box.height) * 1.5
    search = _clip_box(
        BoundingBox(
            track.box.x - margin,
            track.box.y - margin,
            track.box.width + margin * 2,
            track.box.height + margin * 2,
        ),
        gray.shape[1],
        gray.shape[0],
    )
    x, y, width, height = _integer_box(search)
    search_pixels = gray[y : y + height, x : x + width]
    if search_pixels.shape[0] < track.template.shape[0] or search_pixels.shape[1] < track.template.shape[1]:
        return None
    scores = cv2.matchTemplate(search_pixels, track.template, cv2.TM_CCOEFF_NORMED)
    _, maximum, _, location = cv2.minMaxLoc(scores)
    if not math.isfinite(maximum) or maximum < 0.2:
        return None
    return (
        BoundingBox(
            float(x + location[0]),
            float(y + location[1]),
            float(track.template.shape[1]),
            float(track.template.shape[0]),
        ),
        float(maximum),
    )


def _best_ball_candidate(frame: ColorFrame) -> BoundingBox | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((3, 70, 50), dtype=np.uint8), np.array((28, 255, 255), dtype=np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, BoundingBox]] = []
    frame_area = frame.shape[0] * frame.shape[1]
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < frame_area * 0.00001 or area > frame_area * 0.025:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        aspect = width / max(1, height)
        perimeter = float(cv2.arcLength(contour, True))
        circularity = 0.0 if perimeter == 0 else 4 * math.pi * area / (perimeter * perimeter)
        if 0.55 <= aspect <= 1.8 and circularity >= 0.35:
            candidates.append((circularity * area, BoundingBox(float(x), float(y), float(width), float(height))))
    return max(candidates, default=(0.0, None), key=lambda item: item[0])[1]


def _best_rim_candidate(frame: ColorFrame) -> BoundingBox | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    first = cv2.inRange(hsv, np.array((0, 90, 60), dtype=np.uint8), np.array((15, 255, 255), dtype=np.uint8))
    second = cv2.inRange(hsv, np.array((165, 90, 60), dtype=np.uint8), np.array((179, 255, 255), dtype=np.uint8))
    combined = cv2.bitwise_or(first, second)
    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, BoundingBox]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width >= 12 and width >= height * 1.8 and y < frame.shape[0] * 0.8:
            candidates.append((float(width * height), BoundingBox(float(x), float(y), float(width), float(height))))
    return max(candidates, default=(0.0, None), key=lambda item: item[0])[1]


def _clip_box(box: BoundingBox, width: int, height: int) -> BoundingBox:
    x = min(max(0.0, box.x), width - 1.0)
    y = min(max(0.0, box.y), height - 1.0)
    return BoundingBox(x, y, max(1.0, min(box.width, width - x)), max(1.0, min(box.height, height - y)))


def _integer_box(box: BoundingBox) -> tuple[int, int, int, int]:
    return round(box.x), round(box.y), max(1, round(box.width)), max(1, round(box.height))
