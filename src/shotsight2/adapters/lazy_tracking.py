"""Shared lazy boundary for optional model-backed tracking adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from shotsight2.domain.tracking import (
    CameraSegmentInput,
    FrameBatch,
    ModelConfig,
    TrackingBatchResult,
    TrackingPrompt,
    TrackingSession,
    TrackingSummary,
)
from shotsight2.domain.tracking_backends import BackendCapabilities
from shotsight2.ports.tracking import TrackingBackend

RuntimeFactory = Callable[[ModelConfig], TrackingBackend]


class OptionalTrackingBackendUnavailable(RuntimeError):
    """Raised only when an explicitly selected optional backend is loaded."""


class LazyTrackingBackend:
    """Delegate the contract after an optional runtime is explicitly loaded."""

    def __init__(
        self,
        capabilities: BackendCapabilities,
        runtime_factory: RuntimeFactory,
        display_name: str,
    ) -> None:
        self._capabilities = capabilities
        self._runtime_factory = runtime_factory
        self._display_name = display_name
        self._runtime: TrackingBackend | None = None

    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def load(self, model_config: ModelConfig) -> None:
        if self._runtime is not None:
            raise RuntimeError(f"{self._display_name} is already loaded")
        runtime = self._runtime_factory(model_config)
        runtime.load(model_config)
        self._runtime = runtime

    def start_segment(
        self,
        segment: CameraSegmentInput,
        prompts: Sequence[TrackingPrompt],
    ) -> TrackingSession:
        return self._loaded().start_segment(segment, prompts)

    def process_batch(self, session: TrackingSession, frames: FrameBatch) -> TrackingBatchResult:
        return self._loaded().process_batch(session, frames)

    def add_prompt(self, session: TrackingSession, prompt: TrackingPrompt) -> None:
        self._loaded().add_prompt(session, prompt)

    def close_segment(self, session: TrackingSession) -> TrackingSummary:
        return self._loaded().close_segment(session)

    def unload(self) -> None:
        if self._runtime is not None:
            self._runtime.unload()
            self._runtime = None

    def _loaded(self) -> TrackingBackend:
        if self._runtime is None:
            raise RuntimeError(f"{self._display_name} must be loaded before use")
        return self._runtime
