"""Tracking orchestration, prompt, quality, and reset tests."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

import numpy as np
import pytest

from shotsight2.domain.tracking import (
    BoundingBox,
    CameraSegmentInput,
    FrameBatch,
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
from shotsight2.services.tracking import TrackingOrchestrator, automatic_tracking_prompts


class _MemoryPrompts:
    def __init__(self) -> None:
        self.items: list[TrackingPrompt] = []

    def add(self, prompt: TrackingPrompt) -> None:
        self.items.append(prompt)

    def list_for_segment(self, segment_id: str) -> list[TrackingPrompt]:
        return [item for item in self.items if item.segment_id == segment_id]


class _MemoryObservations:
    def __init__(self) -> None:
        self.items: dict[str, list[TrackObservation]] = {}

    def replace_for_segment(self, segment_id: str, observations: Sequence[TrackObservation]) -> None:
        self.items[segment_id] = list(observations)

    def list_for_segment(self, segment_id: str) -> list[TrackObservation]:
        return self.items.get(segment_id, [])

    def list_for_run(self, run_id: str) -> list[TrackObservation]:
        del run_id
        return [item for values in self.items.values() for item in values]


class _Frames:
    def batches(self, segment: CameraSegmentInput) -> Iterable[FrameBatch]:
        del segment
        pixels = np.zeros((100, 200, 3), dtype=np.uint8)
        yield FrameBatch(
            (
                TrackingFrame(0, 0, pixels),
                TrackingFrame(1, 0.1, pixels),
                TrackingFrame(8, 0.8, pixels),
            )
        )


class _Backend:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.segment_ids: list[str] = []

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            (DeviceType.CPU,),
        )

    def load(self, model_config: ModelConfig) -> None:
        del model_config

    def start_segment(
        self,
        segment: CameraSegmentInput,
        prompts: Sequence[TrackingPrompt],
    ) -> TrackingSession:
        assert {prompt.object_class for prompt in prompts} >= set(TrackedObjectClass)
        session = TrackingSession(f"session-{len(self.sessions)}", segment.id, "fake")
        self.sessions.append(session.id)
        self.segment_ids.append(segment.id)
        return session

    def process_batch(self, session: TrackingSession, frames: FrameBatch) -> TrackingBatchResult:
        first = _observation(session, frames.frames[0], BoundingBox(20, 20, 8, 8))
        impossible = _observation(session, frames.frames[1], BoundingBox(190, 90, 8, 8))
        return TrackingBatchResult((first, impossible))

    def add_prompt(self, session: TrackingSession, prompt: TrackingPrompt) -> None:
        del session, prompt

    def close_segment(self, session: TrackingSession) -> TrackingSummary:
        return TrackingSummary(session.id, session.segment_id, "fake", 2, TrackingMetrics(3, 2, 0, 0, 0, 0))

    def unload(self) -> None:
        return None


def test_orchestration_generates_prompts_persists_evidence_and_flags_quality() -> None:
    backend = _Backend()
    prompts = _MemoryPrompts()
    observations = _MemoryObservations()
    service = TrackingOrchestrator(backend, _Frames(), observations, prompts)
    segment = CameraSegmentInput("segment-1", "run-1", 0, 1, 200, 100, 10)

    result = service.track_segment(segment)

    assert {item.object_class for item in prompts.items} == set(TrackedObjectClass)
    assert len(result.observations) == 1
    assert observations.list_for_segment(segment.id) == list(result.observations)
    assert result.summary.metrics.identity_switches == 1
    assert result.summary.metrics.coverage == pytest.approx(1 / 3)


def test_each_camera_segment_gets_a_completely_new_session() -> None:
    backend = _Backend()
    service = TrackingOrchestrator(backend, _Frames(), _MemoryObservations(), _MemoryPrompts())

    service.track_segment(CameraSegmentInput("segment-1", "run-1", 0, 1, 200, 100, 10))
    service.track_segment(CameraSegmentInput("segment-2", "run-1", 1, 2, 200, 100, 10))

    assert backend.sessions == ["session-0", "session-1"]
    assert backend.segment_ids == ["segment-1", "segment-2"]


def test_saved_repair_prompt_requires_user_point_or_box() -> None:
    prompts = _MemoryPrompts()
    service = TrackingOrchestrator(_Backend(), _Frames(), _MemoryObservations(), prompts)
    concept = automatic_tracking_prompts(CameraSegmentInput("segment", "run", 0, 1, 100, 100, 10))[0]

    with pytest.raises(ValueError, match="user"):
        service.save_user_prompt(concept)
    with pytest.raises(ValueError, match="point and box"):
        service.save_user_prompt(replace(concept, source=PromptSource.USER))


def _observation(
    session: TrackingSession,
    frame: TrackingFrame,
    box: BoundingBox,
) -> TrackObservation:
    return TrackObservation(
        id=f"obs-{frame.frame_index}",
        segment_id=session.segment_id,
        frame_index=frame.frame_index,
        timestamp_seconds=frame.timestamp_seconds,
        object_class=TrackedObjectClass.BASKETBALL,
        local_track_id="ball-1",
        bounding_box=box,
        centroid=box.centroid,
        confidence=0.8,
        visibility=VisibilityState.VISIBLE,
        occluded=False,
        provenance=ObservationProvenance("fake", "1", "fake", session.id),
    )
