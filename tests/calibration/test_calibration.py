"""Calibration geometry and service tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from shotsight2.domain import Calibration, CameraSegment
from shotsight2.domain.calibration import (
    CalibrationProposal,
    CalibrationUncertaintyReason,
    CalibrationValidity,
    CourtReferenceObservation,
    ImagePoint,
    NBACourtReferencePoint,
    RimGeometry,
    assess_calibration_geometry,
    build_calibration_geometry,
)
from shotsight2.services.calibration import (
    CalibrationRecalculationRequest,
    CalibrationService,
    CalibrationValidationError,
    CorrectCalibrationCommand,
)

NOW = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)


class MemorySegmentRepository:
    """In-memory camera segment repository for service tests."""

    def __init__(self, segments: Sequence[CameraSegment]) -> None:
        self._segments = {segment.id: segment for segment in segments}

    def replace_for_run(self, run_id: str, segments: Sequence[CameraSegment]) -> None:
        self._segments = {segment.id: segment for segment in segments if segment.analysis_run_id == run_id}

    def get(self, segment_id: str) -> CameraSegment | None:
        return self._segments.get(segment_id)

    def list_for_run(self, run_id: str) -> list[CameraSegment]:
        return [
            segment
            for segment in sorted(self._segments.values(), key=lambda item: (item.start_seconds, item.id))
            if segment.analysis_run_id == run_id
        ]


class MemoryCalibrationRepository:
    """In-memory append-only calibration repository."""

    def __init__(self) -> None:
        self.items: list[Calibration] = []

    def add(self, calibration: Calibration) -> None:
        self.items.append(calibration)

    def list_for_segment(self, segment_id: str) -> list[Calibration]:
        return [calibration for calibration in self.items if calibration.segment_id == segment_id]

    def latest_for_segment(self, segment_id: str) -> Calibration | None:
        matches = self.list_for_segment(segment_id)
        return max(matches, key=lambda item: (item.created_at, item.id), default=None)


class RecordingRecalculationTrigger:
    """Capture downstream recalculation requests."""

    def __init__(self) -> None:
        self.requests: list[CalibrationRecalculationRequest] = []

    def request_recalculation(self, request: CalibrationRecalculationRequest) -> None:
        self.requests.append(request)


def test_valid_nba_geometry_can_produce_precise_calibration() -> None:
    """Complete ordered NBA references and rim geometry are metric-capable."""
    geometry = build_calibration_geometry(
        CalibrationProposal(
            "segment-1",
            rim_candidates=(_rim(0.91),),
            court_points=_court_points(),
        )
    )

    assert geometry.assessment.validity is CalibrationValidity.PRECISE
    assert geometry.assessment.indicative_only is False
    assert geometry.assessment.reasons == ()
    assert geometry.court_points_json()["required_points"] == [
        "left_baseline_corner",
        "right_baseline_corner",
        "right_free_throw_lane",
        "left_free_throw_lane",
    ]


def test_incomplete_markings_fall_back_to_indicative_geometry() -> None:
    """Invisible required markings must not unlock metric coordinates."""
    assessment = assess_calibration_geometry(
        _rim(0.85),
        _court_points()[:2],
    )

    assert assessment.validity is CalibrationValidity.INDICATIVE
    assert assessment.indicative_only is True
    assert CalibrationUncertaintyReason.INCOMPLETE_COURT_POINTS in assessment.reasons


def test_non_standard_court_is_indicative_even_with_complete_points() -> None:
    """A non-standard court keeps the evidence but suppresses precise coordinates."""
    geometry = build_calibration_geometry(
        CalibrationProposal(
            "segment-1",
            rim_candidates=(_rim(0.92),),
            court_points=_court_points(),
            court_standard_matches_nba=False,
        )
    )

    assert geometry.assessment.validity is CalibrationValidity.INDICATIVE
    assert CalibrationUncertaintyReason.NON_STANDARD_COURT in geometry.assessment.reasons


def test_invalid_point_order_is_rejected_for_precise_user_correction() -> None:
    """Crossed or mislabeled required points cannot be stored as precise."""
    segments = MemorySegmentRepository([_segment("segment-1")])
    calibrations = MemoryCalibrationRepository()
    service = CalibrationService(segments, calibrations)

    with pytest.raises(CalibrationValidationError, match="INVALID_POINT_ORDER"):
        service.correct_segment(
            CorrectCalibrationCommand(
                "segment-1",
                _rim(1.0),
                dict(_invalid_order_points()),
                created_at=NOW,
            )
        )

    assert calibrations.items == []


def test_automatic_calibration_persists_record_for_every_stable_segment() -> None:
    """Multi-camera analysis receives independent automatic or indicative versions."""
    segments = MemorySegmentRepository(
        [
            _segment("stable-a", start=0.0, end=50.0),
            _segment("unstable", start=50.0, end=55.0, status="UNSTABLE"),
            _segment("stable-b", start=55.0, end=100.0),
        ]
    )
    calibrations = MemoryCalibrationRepository()
    service = CalibrationService(segments, calibrations)

    created = service.create_automatic_for_run(
        "run-1",
        [
            CalibrationProposal(
                "stable-a",
                rim_candidates=(_rim(0.89),),
                court_points=_court_points(),
            )
        ],
        created_at=NOW,
    )

    assert [item.segment_id for item in created] == ["stable-a", "stable-b"]
    assert created[0].indicative_only is False
    assert created[1].indicative_only is True
    assert created[1].court_points["validity"] == "INDICATIVE"
    assert calibrations.latest_for_segment("unstable") is None


def test_user_correction_versions_calibration_and_triggers_location_recalculation() -> None:
    """Post-analysis correction appends evidence and asks court mapping to recompute."""
    segments = MemorySegmentRepository([_segment("segment-1", start=12.0, end=42.0)])
    calibrations = MemoryCalibrationRepository()
    trigger = RecordingRecalculationTrigger()
    service = CalibrationService(segments, calibrations, trigger)
    service.create_automatic_for_run("run-1", [], created_at=NOW)

    correction = service.correct_segment(
        CorrectCalibrationCommand(
            "segment-1",
            _rim(1.0),
            dict((point.name, point.point) for point in _court_points()),
            created_at=NOW + timedelta(seconds=10),
        )
    )

    versions = calibrations.list_for_segment("segment-1")
    assert len(versions) == 2
    assert versions[0].source == "AUTOMATIC"
    assert correction.source == "USER"
    assert correction.id != versions[0].id
    assert trigger.requests == [
        CalibrationRecalculationRequest(
            segment_id="segment-1",
            calibration_id=correction.id,
            analysis_run_id="run-1",
            start_seconds=12.0,
            end_seconds=42.0,
            indicative_only=False,
            reason="CALIBRATION_CORRECTED",
        )
    ]


def test_presentation_model_exposes_representative_frame_and_active_geometry() -> None:
    """Future routes can render calibration state without knowing repository JSON."""
    segments = MemorySegmentRepository([_segment("segment-1", representative="frame-1.jpg")])
    calibrations = MemoryCalibrationRepository()
    service = CalibrationService(segments, calibrations)
    service.create_automatic_for_run(
        "run-1",
        [
            CalibrationProposal(
                "segment-1",
                rim_candidates=(_rim(0.9),),
                court_points=_court_points(),
            )
        ],
        created_at=NOW,
    )

    model = service.presentation_models_for_run("run-1")[0]

    assert model.representative_artifact_id == "frame-1.jpg"
    assert model.active_calibration_id is not None
    assert model.rim == _rim(0.9)
    assert {point.name for point in model.court_points} == {point.name for point in _court_points()}
    assert model.indicative_only is False


def _segment(
    segment_id: str,
    *,
    start: float = 0.0,
    end: float = 60.0,
    status: str = "STABLE",
    representative: str | None = None,
) -> CameraSegment:
    return CameraSegment(
        id=segment_id,
        analysis_run_id="run-1",
        start_seconds=start,
        end_seconds=end,
        stability_status=status,
        confidence=0.95,
        representative_artifact_id=representative,
    )


def _rim(confidence: float) -> RimGeometry:
    return RimGeometry(ImagePoint(320.0, 120.0), 22.0, 9.0, confidence)


def _court_points() -> tuple[CourtReferenceObservation, ...]:
    return (
        CourtReferenceObservation(
            NBACourtReferencePoint.LEFT_BASELINE_CORNER,
            ImagePoint(100.0, 420.0),
            0.9,
        ),
        CourtReferenceObservation(
            NBACourtReferencePoint.RIGHT_BASELINE_CORNER,
            ImagePoint(540.0, 420.0),
            0.9,
        ),
        CourtReferenceObservation(
            NBACourtReferencePoint.RIGHT_FREE_THROW_LANE,
            ImagePoint(430.0, 180.0),
            0.86,
        ),
        CourtReferenceObservation(
            NBACourtReferencePoint.LEFT_FREE_THROW_LANE,
            ImagePoint(210.0, 180.0),
            0.87,
        ),
        CourtReferenceObservation(
            NBACourtReferencePoint.FREE_THROW_CENTER,
            ImagePoint(320.0, 175.0),
            0.82,
        ),
    )


def _invalid_order_points() -> tuple[tuple[NBACourtReferencePoint, ImagePoint], ...]:
    return (
        (NBACourtReferencePoint.LEFT_BASELINE_CORNER, ImagePoint(100.0, 420.0)),
        (NBACourtReferencePoint.RIGHT_BASELINE_CORNER, ImagePoint(540.0, 420.0)),
        (NBACourtReferencePoint.RIGHT_FREE_THROW_LANE, ImagePoint(210.0, 180.0)),
        (NBACourtReferencePoint.LEFT_FREE_THROW_LANE, ImagePoint(430.0, 180.0)),
    )
