"""Ports for tracking backends, frame access, and durable evidence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from shotsight2.domain.tracking import (
    CameraSegmentInput,
    FrameBatch,
    ModelConfig,
    TrackingBatchResult,
    TrackingPrompt,
    TrackingSession,
    TrackingSummary,
    TrackObservation,
)
from shotsight2.domain.tracking_backends import BackendCapabilities


class TrackingBackend(Protocol):
    """Capability-oriented contract implemented by every tracker."""

    def capabilities(self) -> BackendCapabilities: ...
    def load(self, model_config: ModelConfig) -> None: ...
    def start_segment(
        self,
        segment: CameraSegmentInput,
        prompts: Sequence[TrackingPrompt],
    ) -> TrackingSession: ...
    def process_batch(self, session: TrackingSession, frames: FrameBatch) -> TrackingBatchResult: ...
    def add_prompt(self, session: TrackingSession, prompt: TrackingPrompt) -> None: ...
    def close_segment(self, session: TrackingSession) -> TrackingSummary: ...
    def unload(self) -> None: ...


class TrackingFrameSource(Protocol):
    """Supply decoded batches for one stable segment."""

    def batches(self, segment: CameraSegmentInput) -> Iterable[FrameBatch]: ...


class TrackingObservationRepository(Protocol):
    """Persist structured observations independently of rendered artifacts."""

    def replace_for_segment(
        self,
        segment_id: str,
        observations: Sequence[TrackObservation],
    ) -> None: ...
    def list_for_segment(self, segment_id: str) -> list[TrackObservation]: ...
    def list_for_run(self, run_id: str) -> list[TrackObservation]: ...


class TrackingPromptRepository(Protocol):
    """Persist automatic and user repair prompts."""

    def add(self, prompt: TrackingPrompt) -> None: ...
    def list_for_segment(self, segment_id: str) -> list[TrackingPrompt]: ...
