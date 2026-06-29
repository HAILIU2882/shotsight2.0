"""Focused contract tests for the concrete MLX SAM 3 image runtime."""

from __future__ import annotations

import importlib

import pytest

from shotsight2.adapters.lazy_tracking import OptionalTrackingBackendUnavailable
from shotsight2.adapters.mlx_sam3 import (
    MLXSam3ImageBackend,
    MLXSam3ImageRuntime,
    MLXSam3RuntimeError,
)
from shotsight2.domain.tracking import (
    BoundingBox,
    CameraSegmentInput,
    FrameBatch,
    ImagePoint,
    MaskReference,
    ModelConfig,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingEventKind,
    TrackingFrame,
    TrackingPrompt,
)


class _FakeProcessor:
    def __init__(self) -> None:
        self.images: list[object] = []
        self.text_prompts: list[str] = []
        self.geometry: list[list[float]] = []

    def set_image(self, image: object, state: dict[str, object] | None = None) -> dict[str, object]:
        del state
        self.images.append(image)
        return {"image": image}

    def reset_all_prompts(self, state: dict[str, object]) -> None:
        state.pop("boxes", None)
        state.pop("scores", None)

    def set_text_prompt(self, prompt: str, state: dict[str, object]) -> dict[str, object]:
        self.text_prompts.append(prompt)
        detections = {
            "basketball": ([[10.0, 20.0, 30.0, 40.0]], [0.91]),
            "basketball player": ([[50.0, 10.0, 100.0, 110.0]], [0.82]),
            "basketball rim": ([[120.0, 15.0, 155.0, 30.0]], [0.73]),
        }
        state["boxes"], state["scores"] = detections[prompt]
        return state

    def add_geometric_prompt(
        self,
        box: list[float],
        label: bool,
        state: dict[str, object],
    ) -> dict[str, object]:
        assert label is True
        self.geometry.append(box)
        center_x, center_y, width, height = box
        state["boxes"] = [
            [
                (center_x - width / 2) * 200,
                (center_y - height / 2) * 120,
                (center_x + width / 2) * 200,
                (center_y + height / 2) * 120,
            ]
        ]
        state["scores"] = [0.96]
        return state


class _SequencedProcessor:
    def __init__(self, detections: dict[str, list[tuple[list[list[float]], list[float]]]]) -> None:
        self._detections = detections
        self.images: list[object] = []
        self.text_prompts: list[str] = []
        self.geometry: list[tuple[int, list[float]]] = []

    def set_image(self, image: object, state: dict[str, object] | None = None) -> dict[str, object]:
        del state
        self.images.append(image)
        return {"image": image, "frame_number": len(self.images) - 1}

    def reset_all_prompts(self, state: dict[str, object]) -> None:
        state.pop("boxes", None)
        state.pop("scores", None)

    def set_text_prompt(self, prompt: str, state: dict[str, object]) -> dict[str, object]:
        self.text_prompts.append(prompt)
        frame_number = state["frame_number"]
        assert isinstance(frame_number, int)
        boxes, scores = self._detections[prompt][frame_number]
        state["boxes"] = boxes
        state["scores"] = scores
        return state

    def add_geometric_prompt(
        self,
        box: list[float],
        label: bool,
        state: dict[str, object],
    ) -> dict[str, object]:
        assert label is True
        frame_number = state["frame_number"]
        assert isinstance(frame_number, int)
        self.geometry.append((frame_number, box))
        return state


def _runtime(processor: _FakeProcessor) -> MLXSam3ImageRuntime:
    return MLXSam3ImageRuntime(
        model_factory=lambda _config: object(),
        processor_factory=lambda _model, _config: processor,
        image_factory=lambda pixels: pixels,
        backend_version="0.1.0-test",
    )


def _sequenced_runtime(processor: _SequencedProcessor) -> MLXSam3ImageRuntime:
    return MLXSam3ImageRuntime(
        model_factory=lambda _config: object(),
        processor_factory=lambda _model, _config: processor,
        image_factory=lambda pixels: pixels,
        backend_version="0.1.0-test",
    )


def _segment(identifier: str = "segment-1") -> CameraSegmentInput:
    return CameraSegmentInput(identifier, "run-1", 0, 1, 200, 120, 10)


def _concepts(segment: CameraSegmentInput) -> tuple[TrackingPrompt, ...]:
    return tuple(
        TrackingPrompt(
            id=f"concept-{object_class.value}",
            segment_id=segment.id,
            timestamp_seconds=0,
            object_class=object_class,
            kind=PromptKind.CONCEPT,
            source=PromptSource.AUTOMATIC,
            text=text,
        )
        for object_class, text in (
            (TrackedObjectClass.BASKETBALL, "basketball"),
            (TrackedObjectClass.PLAYER, "basketball player"),
            (TrackedObjectClass.RIM, "basketball rim"),
        )
    )


def _frame(index: int, timestamp: float) -> TrackingFrame:
    return TrackingFrame(index, timestamp, f"frame-{index}")


def test_concept_prompts_emit_all_classes_and_keep_segment_track_ids() -> None:
    processor = _FakeProcessor()
    runtime = _runtime(processor)
    segment = _segment()
    runtime.load(ModelConfig(options={"confidence_threshold": 0.4}))
    session = runtime.start_segment(segment, _concepts(segment))

    result = runtime.process_batch(session, FrameBatch((_frame(0, 0), _frame(1, 0.1))))

    assert processor.images == ["frame-0", "frame-1"]
    assert {item.object_class for item in result.observations} == set(TrackedObjectClass)
    assert [
        item.local_track_id for item in result.observations if item.object_class is TrackedObjectClass.BASKETBALL
    ] == [
        "basketball-1",
        "basketball-1",
    ]
    basketball = result.observations[0]
    assert basketball.bounding_box == BoundingBox(10, 20, 20, 20)
    assert basketball.confidence == pytest.approx(0.91)
    assert basketball.provenance.backend_name == "mlx-sam3"
    assert basketball.provenance.backend_version == "0.1.0-test"
    assert basketball.provenance.model == "mlx-community/sam3-image"

    summary = runtime.close_segment(session)
    assert summary.observations == 6
    assert summary.metrics.observed_frames == 2
    runtime.unload()


def test_point_and_box_prompts_use_upstream_geometric_box_api() -> None:
    processor = _FakeProcessor()
    runtime = _runtime(processor)
    segment = _segment()
    point = TrackingPrompt(
        id="point-1",
        segment_id=segment.id,
        timestamp_seconds=0,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=PromptKind.POINT,
        source=PromptSource.USER,
        point=ImagePoint(100, 60),
        target_track_id="chosen-ball",
    )
    box = TrackingPrompt(
        id="box-1",
        segment_id=segment.id,
        timestamp_seconds=0.2,
        object_class=TrackedObjectClass.RIM,
        kind=PromptKind.BOX,
        source=PromptSource.USER,
        box=BoundingBox(100, 24, 40, 12),
        target_track_id="chosen-rim",
    )
    runtime.load(ModelConfig(options={"point_box_fraction": 0.05}))
    session = runtime.start_segment(segment, (point, box))

    first = runtime.process_batch(session, FrameBatch((_frame(0, 0),)))
    runtime.add_prompt(
        session,
        TrackingPrompt(
            id="late-player",
            segment_id=segment.id,
            timestamp_seconds=0.2,
            object_class=TrackedObjectClass.PLAYER,
            kind=PromptKind.POINT,
            source=PromptSource.USER,
            point=ImagePoint(40, 80),
            target_track_id="chosen-player",
        ),
    )
    second = runtime.process_batch(session, FrameBatch((_frame(2, 0.2),)))

    assert processor.geometry[0] == pytest.approx([0.5, 0.5, 0.05, 0.05])
    assert processor.geometry[4] == pytest.approx([0.6, 0.25, 0.2, 0.1])
    assert first.observations[0].local_track_id == "chosen-ball"
    assert first.observations[0].provenance.reinitialized is True
    assert {item.local_track_id for item in second.observations} == {
        "chosen-ball",
        "chosen-player",
        "chosen-rim",
    }
    assert {item.local_track_id for item in second.observations if item.provenance.reinitialized} == {
        "chosen-player",
        "chosen-rim",
    }


def test_temporal_box_prompt_accepts_consistent_low_confidence_continuation_across_miss() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                ([[10.0, 20.0, 30.0, 40.0]], [0.8]),
                ([], []),
                ([[12.0, 20.0, 32.0, 40.0]], [0.32]),
            ]
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    runtime.load(
        ModelConfig(
            options={
                "continuation_confidence_threshold": 0.3,
                "temporal_max_gap_frames": 2,
                "temporal_max_gap_seconds": 1.0,
            }
        )
    )
    session = runtime.start_segment(segment, (_concepts(segment)[0],))

    result = runtime.process_batch(
        session,
        FrameBatch((_frame(0, 0), _frame(1, 0.1), _frame(2, 0.2))),
    )

    assert [(item.frame_index, item.local_track_id) for item in result.observations] == [
        (0, "basketball-1"),
        (2, "basketball-1"),
    ]
    assert result.observations[-1].confidence == pytest.approx(0.32)
    assert result.observations[-1].provenance.prompt_id == "concept-basketball"
    assert [frame_number for frame_number, _box in processor.geometry] == [1, 2]
    assert result.events == ()


def test_basketball_selection_is_single_slot_and_prefers_continuation_over_seed() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                (
                    [[80.0, 20.0, 100.0, 40.0], [10.0, 20.0, 30.0, 40.0]],
                    [0.95, 0.7],
                ),
                (
                    [[10.0, 20.0, 30.0, 40.0], [82.0, 20.0, 102.0, 40.0]],
                    [0.99, 0.34],
                ),
                (
                    [[120.0, 20.0, 140.0, 40.0], [84.0, 20.0, 104.0, 40.0]],
                    [0.98, 0.36],
                ),
            ]
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    runtime.load(ModelConfig(options={"continuation_confidence_threshold": 0.3}))
    session = runtime.start_segment(segment, (_concepts(segment)[0],))

    result = runtime.process_batch(
        session,
        FrameBatch((_frame(0, 0), _frame(1, 0.1), _frame(2, 0.2))),
    )

    assert [(item.frame_index, item.local_track_id) for item in result.observations] == [
        (0, "basketball-1"),
        (1, "basketball-1"),
        (2, "basketball-1"),
    ]
    assert [item.bounding_box.x for item in result.observations] == [80.0, 82.0, 84.0]
    assert [item.confidence for item in result.observations] == pytest.approx([0.95, 0.34, 0.36])
    assert [frame_number for frame_number, _box in processor.geometry] == [1, 2]
    assert len({item.frame_index for item in result.observations}) == len(result.observations)


def test_basketball_seed_selects_highest_confidence_detection_only() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                (
                    [
                        [20.0, 20.0, 40.0, 40.0],
                        [80.0, 20.0, 100.0, 40.0],
                        [50.0, 20.0, 70.0, 40.0],
                    ],
                    [0.68, 0.93, 0.82],
                )
            ]
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    runtime.load(ModelConfig(options={"seed_confidence_threshold": 0.5}))
    session = runtime.start_segment(segment, (_concepts(segment)[0],))

    result = runtime.process_batch(session, FrameBatch((_frame(0, 0),)))

    assert len(result.observations) == 1
    assert result.observations[0].bounding_box == BoundingBox(80, 20, 20, 20)
    assert result.observations[0].confidence == pytest.approx(0.93)
    assert result.observations[0].local_track_id == "basketball-1"
    assert processor.geometry == []


def test_temporal_prompt_predicts_velocity_and_clamps_expanded_box() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                ([[140.0, 40.0, 160.0, 60.0]], [0.8]),
                ([[160.0, 40.0, 180.0, 60.0]], [0.8]),
                ([], []),
            ]
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    runtime.load(ModelConfig(options={"temporal_box_expansion_fraction": 0.5}))
    session = runtime.start_segment(segment, (_concepts(segment)[0],))

    runtime.process_batch(session, FrameBatch((_frame(0, 0), _frame(1, 0.1), _frame(2, 0.2))))

    frame_number, final_prompt = processor.geometry[-1]
    assert frame_number == 2
    assert final_prompt == pytest.approx([0.9, 0.4166667, 0.2, 0.3333333])
    center_x, center_y, width, height = final_prompt
    assert 0 <= center_x - width / 2 <= center_x + width / 2 <= 1
    assert 0 <= center_y - height / 2 <= center_y + height / 2 <= 1


def test_temporal_memory_expires_and_reports_new_basketball_identity() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                ([[10.0, 20.0, 30.0, 40.0]], [0.8]),
                ([], []),
                ([], []),
                ([[12.0, 20.0, 32.0, 40.0]], [0.8]),
            ]
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    runtime.load(ModelConfig(options={"temporal_max_gap_frames": 1, "temporal_max_gap_seconds": 10.0}))
    session = runtime.start_segment(segment, (_concepts(segment)[0],))

    result = runtime.process_batch(
        session,
        FrameBatch((_frame(0, 0), _frame(1, 0.1), _frame(2, 0.2), _frame(3, 0.3))),
    )

    assert [frame_number for frame_number, _box in processor.geometry] == [1, 2]
    assert [item.local_track_id for item in result.observations] == ["basketball-1", "basketball-2"]
    assert [event.kind for event in result.events] == [TrackingEventKind.IDENTITY_SWITCH]
    assert runtime.close_segment(session).metrics.identity_switches == 1


def test_temporal_continuation_is_basketball_only_and_rejects_inconsistent_low_scores() -> None:
    processor = _SequencedProcessor(
        {
            "basketball": [
                ([[10.0, 20.0, 30.0, 40.0]], [0.8]),
                ([[150.0, 80.0, 195.0, 118.0]], [0.32]),
            ],
            "basketball player": [
                ([[50.0, 10.0, 100.0, 110.0]], [0.8]),
                ([[52.0, 10.0, 102.0, 110.0]], [0.32]),
            ],
        }
    )
    runtime = _sequenced_runtime(processor)
    segment = _segment()
    concepts = tuple(
        prompt
        for prompt in _concepts(segment)
        if prompt.object_class in {TrackedObjectClass.BASKETBALL, TrackedObjectClass.PLAYER}
    )
    runtime.load(ModelConfig(options={"continuation_confidence_threshold": 0.3}))
    session = runtime.start_segment(segment, concepts)

    result = runtime.process_batch(session, FrameBatch((_frame(0, 0), _frame(1, 0.1))))

    assert [(item.frame_index, item.object_class) for item in result.observations] == [
        (0, TrackedObjectClass.BASKETBALL),
        (0, TrackedObjectClass.PLAYER),
    ]
    assert len(processor.geometry) == 1
    assert processor.geometry[0][0] == 1


def test_runtime_rejects_mask_cross_segment_and_closed_sessions() -> None:
    runtime = _runtime(_FakeProcessor())
    runtime.load(ModelConfig())
    segment = _segment()
    wrong = TrackingPrompt(
        id="wrong",
        segment_id="other",
        timestamp_seconds=0,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=PromptKind.POINT,
        source=PromptSource.USER,
        point=ImagePoint(1, 1),
    )
    with pytest.raises(ValueError, match="segment"):
        runtime.start_segment(segment, (wrong,))

    mask = TrackingPrompt(
        id="mask",
        segment_id=segment.id,
        timestamp_seconds=0,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=PromptKind.MASK,
        source=PromptSource.USER,
        mask=MaskReference("mask-artifact", 0),
    )
    session = runtime.start_segment(segment, ())
    with pytest.raises(ValueError, match="mask prompts"):
        runtime.add_prompt(session, mask)
    runtime.close_segment(session)
    with pytest.raises(MLXSam3RuntimeError, match="Unknown or closed"):
        runtime.process_batch(session, FrameBatch((_frame(0, 0),)))


def test_lazy_backend_reports_missing_upstream_module(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def missing_sam3(name: str) -> object:
        if name == "sam3":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", missing_sam3)
    backend = MLXSam3ImageBackend()

    with pytest.raises(OptionalTrackingBackendUnavailable, match="mlx-sam3"):
        backend.load(ModelConfig())
