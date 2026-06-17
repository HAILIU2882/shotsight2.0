"""Reusable contract tests for every runnable tracking adapter."""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np
import pytest

from shotsight2.adapters.mlx_sam3 import MLXSam3ImageBackend
from shotsight2.adapters.opencv import OpenCVTrackingBackend
from shotsight2.adapters.sam3_video import Sam31VideoBackend
from shotsight2.domain.tracking import (
    CameraSegmentInput,
    FrameBatch,
    ImagePoint,
    ModelConfig,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingFrame,
    TrackingPrompt,
)
from shotsight2.ports.tracking import TrackingBackend

BackendFactory = Callable[[], TrackingBackend]


@pytest.fixture(
    params=[
        pytest.param(lambda: OpenCVTrackingBackend(), id="opencv"),
        pytest.param(
            lambda: MLXSam3ImageBackend(runtime_factory=lambda _: OpenCVTrackingBackend()),
            id="mlx-boundary",
        ),
        pytest.param(
            lambda: Sam31VideoBackend(runtime_factory=lambda _: OpenCVTrackingBackend()),
            id="sam31-boundary",
        ),
    ]
)
def backend_factory(request: pytest.FixtureRequest) -> BackendFactory:
    """Return every adapter with optional runtimes replaced by contract fakes."""

    return request.param  # type: ignore[no-any-return]


def test_backend_contract_lifecycle_and_prompt_repair(backend_factory: BackendFactory) -> None:
    """Every backend must expose one lifecycle and observation shape."""

    backend = backend_factory()
    segment = CameraSegmentInput("segment-1", "run-1", 0, 1, 160, 90, 10)
    prompt = TrackingPrompt(
        id="repair-1",
        segment_id=segment.id,
        timestamp_seconds=0,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=PromptKind.POINT,
        source=PromptSource.USER,
        point=ImagePoint(30, 40),
    )
    backend.load(ModelConfig())
    session = backend.start_segment(segment, [prompt])
    result = backend.process_batch(session, FrameBatch((_frame(0, 0), _frame(1, 0.1))))

    assert session.segment_id == segment.id
    assert result.observations
    observation = result.observations[0]
    assert observation.segment_id == segment.id
    assert observation.provenance.session_id == session.id
    assert 0 <= observation.confidence <= 1
    assert observation.bounding_box.area > 0

    summary = backend.close_segment(session)
    assert summary.session_id == session.id
    assert summary.segment_id == segment.id
    backend.unload()


def test_backend_contract_rejects_cross_segment_prompts(backend_factory: BackendFactory) -> None:
    backend = backend_factory()
    backend.load(ModelConfig())
    segment = CameraSegmentInput("segment-1", "run-1", 0, 1, 160, 90, 10)
    prompt = TrackingPrompt(
        id="wrong",
        segment_id="segment-2",
        timestamp_seconds=0,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=PromptKind.POINT,
        source=PromptSource.USER,
        point=ImagePoint(20, 20),
    )

    with pytest.raises(ValueError, match="segment"):
        backend.start_segment(segment, [prompt])


def _frame(index: int, timestamp: float) -> TrackingFrame:
    pixels = np.zeros((90, 160, 3), dtype=np.uint8)
    cv2.circle(pixels, (30 + index, 40), 5, (0, 140, 255), -1)
    return TrackingFrame(index, timestamp, pixels)
