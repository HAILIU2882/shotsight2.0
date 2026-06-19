"""Segment-scoped tracking orchestration and basketball plausibility rules."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from shotsight2.domain.tracking import (
    BoundingBox,
    CameraSegmentInput,
    ModelConfig,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingEvent,
    TrackingEventKind,
    TrackingMetrics,
    TrackingPrompt,
    TrackingSummary,
    TrackObservation,
    VisibilityState,
)
from shotsight2.ports.tracking import (
    TrackingBackend,
    TrackingFrameSource,
    TrackingObservationRepository,
    TrackingPromptRepository,
)


@dataclass(frozen=True, slots=True)
class TrackingQualityConfig:
    """Thresholds for loss and basketball false-positive rejection."""

    lost_after_seconds: float = 0.5
    maximum_ball_speed_frame_diagonals_per_second: float = 3.5
    minimum_ball_area_ratio: float = 0.00001
    maximum_ball_area_ratio: float = 0.025
    maximum_ball_area_change_ratio: float = 4.0
    maximum_ball_body_overlap: float = 0.85

    def __post_init__(self) -> None:
        if self.lost_after_seconds <= 0 or self.maximum_ball_speed_frame_diagonals_per_second <= 0:
            raise ValueError("Tracking timing and motion thresholds must be positive")
        if not 0 <= self.minimum_ball_area_ratio < self.maximum_ball_area_ratio <= 1:
            raise ValueError("Ball area ratios must be ordered within zero and one")
        if self.maximum_ball_area_change_ratio < 1:
            raise ValueError("Ball area-change ratio must be at least one")
        if not 0 <= self.maximum_ball_body_overlap <= 1:
            raise ValueError("Body overlap must be between zero and one")


@dataclass(frozen=True, slots=True)
class SegmentTrackingResult:
    """Accepted evidence and quality summary for one camera segment."""

    observations: tuple[TrackObservation, ...]
    events: tuple[TrackingEvent, ...]
    summary: TrackingSummary


class TrackingOrchestrator:
    """Run a fresh backend session for each stable camera segment."""

    def __init__(
        self,
        backend: TrackingBackend,
        frame_source: TrackingFrameSource,
        observations: TrackingObservationRepository,
        prompts: TrackingPromptRepository,
        *,
        quality: TrackingQualityConfig | None = None,
        model_config: ModelConfig | None = None,
    ) -> None:
        self._backend = backend
        self._frame_source = frame_source
        self._observations = observations
        self._prompts = prompts
        self._quality = quality or TrackingQualityConfig()
        self._model_config = model_config or ModelConfig()
        self._backend_loaded = False

    def track_segment(self, segment: CameraSegmentInput) -> SegmentTrackingResult:
        """Track one segment with no state inherited from another viewpoint."""

        if not self._backend_loaded:
            self._backend.load(self._model_config)
            self._backend_loaded = True

        automatic = automatic_tracking_prompts(segment)
        saved = tuple(self._prompts.list_for_segment(segment.id))
        known_ids = {prompt.id for prompt in saved}
        for prompt in automatic:
            if prompt.id not in known_ids:
                self._prompts.add(prompt)
        prompts = (*automatic, *(prompt for prompt in saved if prompt.source is PromptSource.USER))
        session = self._backend.start_segment(segment, prompts)
        controller = _TrackingQualityController(segment, self._quality)
        accepted: list[TrackObservation] = []
        events: list[TrackingEvent] = []
        expected_frames = 0

        for batch in self._frame_source.batches(segment):
            expected_frames += len(batch.frames)
            result = self._backend.process_batch(session, batch)
            filtered, quality_events = controller.filter(result.observations, batch.frames[-1].timestamp_seconds)
            accepted.extend(filtered)
            events.extend(result.events)
            events.extend(quality_events)

        backend_summary = self._backend.close_segment(session)
        self._observations.replace_for_segment(segment.id, accepted)
        observed_ball_frames = len(
            {item.frame_index for item in accepted if item.object_class is TrackedObjectClass.BASKETBALL}
        )
        all_events = tuple(events)
        metrics = TrackingMetrics(
            expected_frames=expected_frames,
            observed_frames=observed_ball_frames,
            reinitializations=sum(
                item.provenance.reinitialized for item in accepted if item.object_class is TrackedObjectClass.BASKETBALL
            ),
            identity_switches=sum(item.kind is TrackingEventKind.IDENTITY_SWITCH for item in all_events),
            lost_events=sum(item.kind is TrackingEventKind.TRACK_LOST for item in all_events),
            occlusion_events=sum(item.kind is TrackingEventKind.OCCLUSION for item in all_events),
        )
        summary = TrackingSummary(
            session_id=backend_summary.session_id,
            segment_id=segment.id,
            backend_name=backend_summary.backend_name,
            observations=len(accepted),
            metrics=metrics,
        )
        return SegmentTrackingResult(tuple(accepted), all_events, summary)

    def save_user_prompt(self, prompt: TrackingPrompt) -> None:
        """Persist a point or box repair prompt for full reanalysis."""

        if prompt.source is not PromptSource.USER:
            raise ValueError("Saved repair prompts must be user supplied")
        if prompt.kind not in {PromptKind.POINT, PromptKind.BOX}:
            raise ValueError("Only point and box repair prompts are supported")
        self._prompts.add(prompt)


def automatic_tracking_prompts(segment: CameraSegmentInput) -> tuple[TrackingPrompt, ...]:
    """Create stable concept prompts for all tracking-owned object classes."""

    concepts = (
        (TrackedObjectClass.BASKETBALL, "basketball"),
        (TrackedObjectClass.PLAYER, "basketball player"),
        (TrackedObjectClass.RIM, "basketball rim"),
    )
    return tuple(
        TrackingPrompt(
            id=str(uuid5(NAMESPACE_URL, f"shotsight:{segment.id}:automatic:{object_class.value}")),
            segment_id=segment.id,
            timestamp_seconds=segment.start_seconds,
            object_class=object_class,
            kind=PromptKind.CONCEPT,
            source=PromptSource.AUTOMATIC,
            text=text,
        )
        for object_class, text in concepts
    )


class _TrackingQualityController:
    def __init__(self, segment: CameraSegmentInput, config: TrackingQualityConfig) -> None:
        self._segment = segment
        self._config = config
        self._last_by_track: dict[tuple[TrackedObjectClass, str], TrackObservation] = {}
        self._last_ball: TrackObservation | None = None
        self._loss_reported = False

    def filter(
        self,
        observations: Sequence[TrackObservation],
        batch_end_seconds: float,
    ) -> tuple[tuple[TrackObservation, ...], tuple[TrackingEvent, ...]]:
        players = tuple(item.bounding_box for item in observations if item.object_class is TrackedObjectClass.PLAYER)
        accepted: list[TrackObservation] = []
        events: list[TrackingEvent] = []

        for observation in observations:
            if observation.visibility is VisibilityState.OCCLUDED:
                events.append(_event(TrackingEventKind.OCCLUSION, observation, "Backend marked the object occluded."))
            previous = self._last_by_track.get((observation.object_class, observation.local_track_id))
            rejection = (
                self._basketball_rejection(observation, previous, players)
                if observation.object_class is TrackedObjectClass.BASKETBALL
                else None
            )
            if rejection is not None:
                events.append(_event(TrackingEventKind.REJECTED_IMPLAUSIBLE, observation, rejection))
                if previous is not None:
                    events.append(
                        _event(
                            TrackingEventKind.IDENTITY_SWITCH,
                            observation,
                            "Observation was inconsistent with the prior local identity.",
                        )
                    )
                continue
            accepted.append(observation)
            self._last_by_track[(observation.object_class, observation.local_track_id)] = observation
            if observation.object_class is TrackedObjectClass.BASKETBALL:
                self._last_ball = observation
                self._loss_reported = False
                if observation.provenance.reinitialized:
                    events.append(
                        _event(
                            TrackingEventKind.REINITIALIZED,
                            observation,
                            "User prompt repaired the track.",
                        )
                    )

        if (
            self._last_ball is not None
            and not self._loss_reported
            and batch_end_seconds - self._last_ball.timestamp_seconds > self._config.lost_after_seconds
        ):
            events.append(
                TrackingEvent(
                    kind=TrackingEventKind.TRACK_LOST,
                    timestamp_seconds=batch_end_seconds,
                    object_class=TrackedObjectClass.BASKETBALL,
                    local_track_id=self._last_ball.local_track_id,
                    reason="No plausible basketball observation arrived before the loss threshold.",
                    observation_id=self._last_ball.id,
                )
            )
            self._loss_reported = True
        return tuple(accepted), tuple(events)

    def _basketball_rejection(
        self,
        observation: TrackObservation,
        previous: TrackObservation | None,
        players: Sequence[BoundingBox],
    ) -> str | None:
        frame_area = self._segment.width * self._segment.height
        area_ratio = observation.bounding_box.area / frame_area
        if not self._config.minimum_ball_area_ratio <= area_ratio <= self._config.maximum_ball_area_ratio:
            return "Basketball size is outside the configured frame-area range."

        overlap = max(
            (observation.bounding_box.intersection_area(player) / observation.bounding_box.area for player in players),
            default=0.0,
        )
        if overlap > self._config.maximum_ball_body_overlap:
            return "Basketball candidate overlaps a player body too completely."

        if previous is None:
            return None
        elapsed = observation.timestamp_seconds - previous.timestamp_seconds
        if elapsed <= 0:
            return "Basketball timestamps are not strictly increasing."
        distance = math.hypot(
            observation.centroid.x - previous.centroid.x,
            observation.centroid.y - previous.centroid.y,
        )
        diagonal = math.hypot(self._segment.width, self._segment.height)
        maximum_distance = diagonal * self._config.maximum_ball_speed_frame_diagonals_per_second * elapsed
        if distance > maximum_distance:
            return "Basketball motion exceeds the configured continuity limit."
        area_change = max(
            observation.bounding_box.area / previous.bounding_box.area,
            previous.bounding_box.area / observation.bounding_box.area,
        )
        if area_change > self._config.maximum_ball_area_change_ratio:
            return "Basketball size changed implausibly between adjacent observations."
        return None


def _event(kind: TrackingEventKind, observation: TrackObservation, reason: str) -> TrackingEvent:
    return TrackingEvent(
        kind=kind,
        timestamp_seconds=observation.timestamp_seconds,
        object_class=observation.object_class,
        local_track_id=observation.local_track_id,
        reason=reason,
        observation_id=observation.id,
    )
