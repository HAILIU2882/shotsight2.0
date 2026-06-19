"""Lazy, segment-scoped adapter for the Apple Silicon MLX SAM 3 image model."""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from shotsight2.adapters.lazy_tracking import (
    LazyTrackingBackend,
    OptionalTrackingBackendUnavailable,
    RuntimeFactory,
)
from shotsight2.domain.tracking import (
    BoundingBox,
    CameraSegmentInput,
    FrameBatch,
    ModelConfig,
    ObservationProvenance,
    PromptKind,
    TrackedObjectClass,
    TrackingBatchResult,
    TrackingMetrics,
    TrackingPrompt,
    TrackingSession,
    TrackingSummary,
    TrackObservation,
    VisibilityState,
)
from shotsight2.domain.tracking_backends import BackendCapabilities, DeviceType
from shotsight2.ports.tracking import TrackingBackend

_BACKEND_NAME = "mlx-sam3"
_DEFAULT_MODEL = "mlx-community/sam3-image"


class MLXSam3RuntimeError(RuntimeError):
    """Raised when an MLX SAM 3 runtime lifecycle or result is invalid."""


class Sam3ImageProcessor(Protocol):
    """Small structural boundary around the upstream MLX processor API."""

    def set_image(self, image: object, state: dict[str, object] | None = None) -> dict[str, object]: ...
    def set_text_prompt(self, prompt: str, state: dict[str, object]) -> dict[str, object]: ...
    def add_geometric_prompt(
        self,
        box: list[float],
        label: bool,
        state: dict[str, object],
    ) -> dict[str, object]: ...
    def reset_all_prompts(self, state: dict[str, object]) -> None: ...


ModelFactory = Callable[[ModelConfig], object]
ProcessorFactory = Callable[[object, ModelConfig], Sam3ImageProcessor]
ImageFactory = Callable[[object], object]


@dataclass(slots=True)
class _SegmentState:
    segment: CameraSegmentInput
    prompts: list[TrackingPrompt]
    tracks: dict[TrackedObjectClass, dict[str, BoundingBox]] = field(default_factory=dict)
    next_track_number: dict[TrackedObjectClass, int] = field(default_factory=dict)
    activated_prompt_ids: set[str] = field(default_factory=set)
    observations: int = 0
    observed_ball_frames: set[int] = field(default_factory=set)
    reinitializations: int = 0


class MLXSam3ImageBackend(LazyTrackingBackend):
    """Load the optional MLX image runtime only after backend selection."""

    def __init__(self, runtime_factory: RuntimeFactory | None = None) -> None:
        super().__init__(
            BackendCapabilities(
                text_prompts=True,
                point_prompts=True,
                box_prompts=True,
                mask_prompts=False,
                native_video_memory=False,
                multi_object_tracking=True,
                batch_support=True,
                mask_output=False,
                supported_devices=(DeviceType.APPLE_SILICON,),
                maximum_recommended_resolution=(1008, 1008),
            ),
            runtime_factory or _default_runtime_factory,
            "MLX SAM 3 Image backend",
        )


class MLXSam3ImageRuntime:
    """Adapt independent SAM 3 image detections to ShotSight's tracking contract."""

    _CAPABILITIES = BackendCapabilities(
        text_prompts=True,
        point_prompts=True,
        box_prompts=True,
        mask_prompts=False,
        native_video_memory=False,
        multi_object_tracking=True,
        batch_support=True,
        mask_output=False,
        supported_devices=(DeviceType.APPLE_SILICON,),
        maximum_recommended_resolution=(1008, 1008),
    )

    def __init__(
        self,
        *,
        model_factory: ModelFactory | None = None,
        processor_factory: ProcessorFactory | None = None,
        image_factory: ImageFactory | None = None,
        backend_version: str | None = None,
    ) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._processor_factory = processor_factory or _default_processor_factory
        self._image_factory = image_factory or _to_pil_image
        self._backend_version = backend_version
        self._model: object | None = None
        self._processor: Sam3ImageProcessor | None = None
        self._model_name: str | None = None
        self._point_box_fraction = 0.025
        self._association_distance_fraction = 0.12
        self._sessions: dict[str, _SegmentState] = {}

    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def load(self, model_config: ModelConfig) -> None:
        """Build the optional model and processor exactly once."""

        if self._model is not None:
            raise MLXSam3RuntimeError("MLX SAM 3 runtime is already loaded")
        self._point_box_fraction = _float_option(model_config, "point_box_fraction", 0.025)
        self._association_distance_fraction = _float_option(
            model_config,
            "association_distance_fraction",
            0.12,
        )
        if not 0 < self._point_box_fraction <= 1:
            raise ValueError("point_box_fraction must be between zero and one")
        if not 0 < self._association_distance_fraction <= 1:
            raise ValueError("association_distance_fraction must be between zero and one")
        model = self._model_factory(model_config)
        self._processor = self._processor_factory(model, model_config)
        self._model = model
        self._model_name = _configured_model_name(model_config)

    def start_segment(
        self,
        segment: CameraSegmentInput,
        prompts: Sequence[TrackingPrompt],
    ) -> TrackingSession:
        """Create isolated prompt and association state for one stable camera segment."""

        self._loaded_processor()
        _validate_prompts(segment.id, prompts)
        session = TrackingSession(str(uuid4()), segment.id, _BACKEND_NAME)
        self._sessions[session.id] = _SegmentState(segment=segment, prompts=list(prompts))
        return session

    def process_batch(self, session: TrackingSession, frames: FrameBatch) -> TrackingBatchResult:
        """Run SAM 3 per frame and associate its independent image detections locally."""

        processor = self._loaded_processor()
        state = self._state(session)
        observations: list[TrackObservation] = []
        for frame in frames.frames:
            image_state = processor.set_image(self._image_factory(frame.pixels))
            for object_class in TrackedObjectClass:
                active_prompts = tuple(
                    prompt
                    for prompt in state.prompts
                    if prompt.object_class is object_class and prompt.timestamp_seconds <= frame.timestamp_seconds
                )
                if not active_prompts:
                    continue
                processor.reset_all_prompts(image_state)
                result_state = self._apply_prompts(processor, image_state, active_prompts, state.segment)
                detections = _detections(result_state, state.segment)
                if not detections:
                    state.tracks[object_class] = {}
                    continue
                prompt = _provenance_prompt(active_prompts)
                reinitialized = (
                    prompt is not None
                    and prompt.kind in {PromptKind.POINT, PromptKind.BOX}
                    and prompt.id not in state.activated_prompt_ids
                )
                track_ids = self._associate(
                    state,
                    object_class,
                    tuple(box for box, _score in detections),
                    prompt.target_track_id if prompt is not None else None,
                )
                for (box, confidence), local_track_id in zip(detections, track_ids, strict=True):
                    observation = TrackObservation(
                        id=f"{session.id}:{frame.frame_index}:{object_class.value}:{local_track_id}",
                        segment_id=state.segment.id,
                        frame_index=frame.frame_index,
                        timestamp_seconds=frame.timestamp_seconds,
                        object_class=object_class,
                        local_track_id=local_track_id,
                        bounding_box=box,
                        centroid=box.centroid,
                        confidence=confidence,
                        visibility=VisibilityState.VISIBLE,
                        occluded=False,
                        provenance=ObservationProvenance(
                            backend_name=_BACKEND_NAME,
                            backend_version=self._backend_version,
                            model=self._model_name,
                            session_id=session.id,
                            prompt_id=prompt.id if prompt is not None else None,
                            reinitialized=reinitialized,
                        ),
                    )
                    observations.append(observation)
                    state.observations += 1
                    if object_class is TrackedObjectClass.BASKETBALL:
                        state.observed_ball_frames.add(frame.frame_index)
                    if reinitialized:
                        state.reinitializations += 1
                state.activated_prompt_ids.update(
                    active.id for active in active_prompts if active.kind in {PromptKind.POINT, PromptKind.BOX}
                )
        return TrackingBatchResult(tuple(observations))

    def add_prompt(self, session: TrackingSession, prompt: TrackingPrompt) -> None:
        """Add a repair prompt that becomes active at its timestamp."""

        state = self._state(session)
        _validate_prompts(state.segment.id, (prompt,))
        state.prompts.append(prompt)

    def close_segment(self, session: TrackingSession) -> TrackingSummary:
        """Return segment metrics and discard all segment-local associations."""

        state = self._state(session)
        del self._sessions[session.id]
        expected = max(1, round((state.segment.end_seconds - state.segment.start_seconds) * state.segment.fps))
        return TrackingSummary(
            session_id=session.id,
            segment_id=session.segment_id,
            backend_name=session.backend_name,
            observations=state.observations,
            metrics=TrackingMetrics(
                expected_frames=expected,
                observed_frames=len(state.observed_ball_frames),
                reinitializations=state.reinitializations,
                identity_switches=0,
                lost_events=0,
                occlusion_events=0,
            ),
        )

    def unload(self) -> None:
        """Release model references and every open segment session."""

        self._sessions.clear()
        self._processor = None
        self._model = None
        self._model_name = None

    def _apply_prompts(
        self,
        processor: Sam3ImageProcessor,
        image_state: dict[str, object],
        prompts: Sequence[TrackingPrompt],
        segment: CameraSegmentInput,
    ) -> dict[str, object]:
        result = image_state
        concepts = tuple(prompt for prompt in prompts if prompt.kind is PromptKind.CONCEPT)
        geometry = tuple(prompt for prompt in prompts if prompt.kind in {PromptKind.POINT, PromptKind.BOX})
        if concepts:
            text = concepts[-1].text
            if text is None:  # Protected by TrackingPrompt validation; retained for typed safety.
                raise MLXSam3RuntimeError("Concept prompt has no text")
            result = processor.set_text_prompt(text, result)
        for prompt in geometry:
            result = processor.add_geometric_prompt(
                _normalized_prompt_box(prompt, segment, self._point_box_fraction),
                True,
                result,
            )
        return result

    def _associate(
        self,
        state: _SegmentState,
        object_class: TrackedObjectClass,
        boxes: Sequence[BoundingBox],
        preferred_track_id: str | None,
    ) -> tuple[str, ...]:
        previous = state.tracks.get(object_class, {})
        available = set(previous)
        assigned: list[str] = []
        current: dict[str, BoundingBox] = {}
        diagonal = math.hypot(state.segment.width, state.segment.height)

        for index, box in enumerate(boxes):
            if index == 0 and preferred_track_id:
                track_id = preferred_track_id
                available.discard(track_id)
            else:
                matched_track_id = _best_previous_track(
                    box,
                    previous,
                    available,
                    diagonal * self._association_distance_fraction,
                )
                if matched_track_id is None:
                    number = state.next_track_number.get(object_class, 1)
                    track_id = f"{object_class.value}-{number}"
                    state.next_track_number[object_class] = number + 1
                else:
                    track_id = matched_track_id
                available.discard(track_id)
            assigned.append(track_id)
            current[track_id] = box
        state.tracks[object_class] = current
        return tuple(assigned)

    def _loaded_processor(self) -> Sam3ImageProcessor:
        if self._processor is None:
            raise MLXSam3RuntimeError("MLX SAM 3 runtime must be loaded before use")
        return self._processor

    def _state(self, session: TrackingSession) -> _SegmentState:
        try:
            state = self._sessions[session.id]
        except KeyError as error:
            raise MLXSam3RuntimeError("Unknown or closed MLX SAM 3 tracking session") from error
        if session.segment_id != state.segment.id or session.backend_name != _BACKEND_NAME:
            raise MLXSam3RuntimeError("Tracking session does not match MLX SAM 3 segment state")
        return state


def _default_runtime_factory(config: ModelConfig) -> TrackingBackend:
    """Create the concrete runtime while leaving optional imports for ``load``."""

    del config
    return MLXSam3ImageRuntime()


def _default_model_factory(config: ModelConfig) -> object:
    try:
        module = importlib.import_module("sam3")
    except (ImportError, ModuleNotFoundError) as error:
        raise OptionalTrackingBackendUnavailable(
            "MLX SAM 3 cannot load: distribution 'mlx-sam3' (Python module 'sam3') is not installed."
        ) from error
    builder = getattr(module, "build_sam3_image_model", None)
    if not callable(builder):
        raise OptionalTrackingBackendUnavailable("Installed 'sam3' module does not expose build_sam3_image_model.")

    options: dict[str, object] = {}
    if config.model_path:
        model_path = Path(config.model_path)
        key = "local_weights_dir" if model_path.is_dir() else "checkpoint_path"
        options[key] = str(model_path)
    hf_repo = config.options.get("hf_repo")
    if isinstance(hf_repo, str) and hf_repo:
        options["hf_repo"] = hf_repo
    for name in ("compile", "enable_segmentation", "enable_inst_interactivity"):
        value = config.options.get(name)
        if isinstance(value, bool):
            options[name] = value
    return cast(Callable[..., object], builder)(**options)


def _default_processor_factory(model: object, config: ModelConfig) -> Sam3ImageProcessor:
    try:
        module = importlib.import_module("sam3.model.sam3_image_processor")
    except (ImportError, ModuleNotFoundError) as error:
        raise OptionalTrackingBackendUnavailable(
            "MLX SAM 3 cannot load Sam3Processor from sam3.model.sam3_image_processor."
        ) from error
    processor_type = getattr(module, "Sam3Processor", None)
    if not callable(processor_type):
        raise OptionalTrackingBackendUnavailable("Installed MLX SAM 3 package does not expose Sam3Processor.")
    resolution = _int_option(config, "resolution", 1008)
    confidence = _float_option(config, "confidence_threshold", 0.5)
    processor = cast(Callable[..., object], processor_type)(
        model,
        resolution=resolution,
        confidence_threshold=confidence,
    )
    return cast(Sam3ImageProcessor, processor)


def _to_pil_image(pixels: object) -> object:
    """Convert OpenCV BGR frames to the PIL RGB input required upstream."""

    try:
        image_module = importlib.import_module("PIL.Image")
    except (ImportError, ModuleNotFoundError) as error:
        raise OptionalTrackingBackendUnavailable(
            "MLX SAM 3 frame conversion requires the optional 'Pillow' package."
        ) from error
    dynamic_image_module = cast(Any, image_module)
    image_type = dynamic_image_module.Image
    if isinstance(pixels, image_type):
        return pixels
    dynamic_pixels = cast(Any, pixels)
    shape = getattr(dynamic_pixels, "shape", None)
    if not isinstance(shape, tuple) or len(shape) != 3 or shape[2] not in {3, 4}:
        raise TypeError("MLX SAM 3 frames must be PIL images or HxWx3/HxWx4 arrays")
    rgb_pixels = dynamic_pixels[:, :, [2, 1, 0]] if shape[2] == 3 else dynamic_pixels[:, :, [2, 1, 0, 3]]
    return cast(Callable[[object], object], dynamic_image_module.fromarray)(rgb_pixels)


def _validate_prompts(segment_id: str, prompts: Sequence[TrackingPrompt]) -> None:
    if any(prompt.segment_id != segment_id for prompt in prompts):
        raise ValueError("Every prompt must belong to the started segment")
    unsupported = tuple(prompt for prompt in prompts if prompt.kind is PromptKind.MASK)
    if unsupported:
        raise ValueError("MLX SAM 3 Image does not support mask prompts")


def _normalized_prompt_box(
    prompt: TrackingPrompt,
    segment: CameraSegmentInput,
    point_box_fraction: float,
) -> list[float]:
    if prompt.box is not None:
        center = prompt.box.centroid
        width = prompt.box.width / segment.width
        height = prompt.box.height / segment.height
    elif prompt.point is not None:
        center = prompt.point
        width = max(point_box_fraction, 2 / segment.width)
        height = max(point_box_fraction, 2 / segment.height)
    else:
        raise MLXSam3RuntimeError("Geometric prompt contains neither a point nor a box")
    return [
        _clamp(center.x / segment.width, 0.0, 1.0),
        _clamp(center.y / segment.height, 0.0, 1.0),
        _clamp(width, 2 / segment.width, 1.0),
        _clamp(height, 2 / segment.height, 1.0),
    ]


def _detections(
    result_state: dict[str, object],
    segment: CameraSegmentInput,
) -> tuple[tuple[BoundingBox, float], ...]:
    boxes = _as_rows(result_state.get("boxes"))
    scores = _as_scalars(result_state.get("scores"))
    count = min(len(boxes), len(scores))
    detections: list[tuple[BoundingBox, float]] = []
    for values, score in zip(boxes[:count], scores[:count], strict=True):
        if len(values) < 4:
            continue
        left = _clamp(float(values[0]), 0.0, float(segment.width))
        top = _clamp(float(values[1]), 0.0, float(segment.height))
        right = _clamp(float(values[2]), 0.0, float(segment.width))
        bottom = _clamp(float(values[3]), 0.0, float(segment.height))
        if right <= left or bottom <= top:
            continue
        detections.append(
            (
                BoundingBox(left, top, right - left, bottom - top),
                _clamp(float(score), 0.0, 1.0),
            )
        )
    detections.sort(key=lambda item: (-item[1], item[0].x, item[0].y))
    return tuple(detections)


def _as_rows(value: object | None) -> list[list[float]]:
    converted = _to_python(value)
    if not isinstance(converted, (list, tuple)):
        return []
    rows: list[list[float]] = []
    for row in converted:
        if isinstance(row, (list, tuple)):
            rows.append([float(item) for item in row])
    return rows


def _as_scalars(value: object | None) -> list[float]:
    converted = _to_python(value)
    if not isinstance(converted, (list, tuple)):
        return []
    return [float(item) for item in converted]


def _to_python(value: object | None) -> object:
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return cast(Callable[[], object], tolist)()
    return value


def _provenance_prompt(prompts: Sequence[TrackingPrompt]) -> TrackingPrompt | None:
    geometry = tuple(prompt for prompt in prompts if prompt.kind in {PromptKind.POINT, PromptKind.BOX})
    if geometry:
        return max(geometry, key=lambda prompt: (prompt.timestamp_seconds, prompt.id))
    concepts = tuple(prompt for prompt in prompts if prompt.kind is PromptKind.CONCEPT)
    return concepts[-1] if concepts else None


def _best_previous_track(
    box: BoundingBox,
    previous: dict[str, BoundingBox],
    available: set[str],
    maximum_distance: float,
) -> str | None:
    best_id: str | None = None
    best_rank: tuple[float, float] | None = None
    for track_id in sorted(available):
        candidate = previous[track_id]
        union = box.area + candidate.area - box.intersection_area(candidate)
        overlap = box.intersection_area(candidate) / union if union > 0 else 0.0
        distance = math.hypot(
            box.centroid.x - candidate.centroid.x,
            box.centroid.y - candidate.centroid.y,
        )
        if overlap <= 0 and distance > maximum_distance:
            continue
        rank = (overlap, -distance)
        if best_rank is None or rank > best_rank:
            best_id = track_id
            best_rank = rank
    return best_id


def _configured_model_name(config: ModelConfig) -> str:
    if config.model_path:
        return Path(config.model_path).name
    hf_repo = config.options.get("hf_repo")
    return hf_repo if isinstance(hf_repo, str) and hf_repo else _DEFAULT_MODEL


def _float_option(config: ModelConfig, name: str, default: float) -> float:
    value = config.options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _int_option(config: ModelConfig, name: str, default: int) -> int:
    value = config.options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
