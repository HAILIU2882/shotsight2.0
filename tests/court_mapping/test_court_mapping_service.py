"""Court mapping orchestration and recalculation tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from shotsight2.domain import Calibration, CameraSegment, ShotAttempt, ShotLocation
from shotsight2.domain.calibration import (
    FOOT_TO_METER,
    CalibrationAssessment,
    CalibrationGeometry,
    CalibrationValidity,
    CourtCoordinate,
    CourtReferenceObservation,
    ImagePoint,
    NBACourtReferencePoint,
    RimGeometry,
)
from shotsight2.domain.court import NormalizedCourtCoordinate, ShotValue
from shotsight2.domain.persistence import ReviewStatus, ShotOutcome
from shotsight2.domain.release_position import ImageBoundingBox, ReleasePlayerObservation
from shotsight2.services.calibration import CalibrationRecalculationRequest
from shotsight2.services.court_mapping import (
    CourtMappingService,
    LocationMissingReason,
    LocationSource,
    ManualLocation,
)

NOW = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)


class MemorySegments:
    def __init__(self, items: Sequence[CameraSegment]) -> None:
        self.items = list(items)

    def replace_for_run(self, run_id: str, segments: Sequence[CameraSegment]) -> None:
        self.items = [segment for segment in segments if segment.analysis_run_id == run_id]

    def get(self, segment_id: str) -> CameraSegment | None:
        return next((segment for segment in self.items if segment.id == segment_id), None)

    def list_for_run(self, run_id: str) -> list[CameraSegment]:
        return [segment for segment in self.items if segment.analysis_run_id == run_id]


class MemoryCalibrations:
    def __init__(self, items: Sequence[Calibration]) -> None:
        self.items = list(items)

    def add(self, calibration: Calibration) -> None:
        self.items.append(calibration)

    def list_for_segment(self, segment_id: str) -> list[Calibration]:
        return [item for item in self.items if item.segment_id == segment_id]

    def latest_for_segment(self, segment_id: str) -> Calibration | None:
        return max(self.list_for_segment(segment_id), key=lambda item: (item.created_at, item.id), default=None)


class MemoryAttempts:
    def __init__(self, items: Sequence[ShotAttempt]) -> None:
        self.items = list(items)
        self.locations: dict[str, ShotLocation] = {}

    def list_for_run(self, run_id: str) -> list[ShotAttempt]:
        return [item for item in self.items if item.analysis_run_id == run_id]

    def update_location_and_shot_type(
        self,
        attempt_id: str,
        location: ShotLocation,
        shot_type: str,
    ) -> None:
        self.locations[attempt_id] = location
        self.items = [replace(item, shot_type=shot_type) if item.id == attempt_id else item for item in self.items]

    def clear_location_and_shot_type(self, attempt_id: str, shot_type: str) -> None:
        self.locations.pop(attempt_id, None)
        self.items = [replace(item, shot_type=shot_type) if item.id == attempt_id else item for item in self.items]


class MemoryObservations:
    def __init__(self, items: dict[tuple[str, str], ReleasePlayerObservation]) -> None:
        self.items = items

    def for_attempt(
        self,
        attempt: ShotAttempt,
        shooter_track_id: str,
    ) -> ReleasePlayerObservation | None:
        return self.items.get((attempt.id, shooter_track_id))


def test_precise_calibration_maps_release_foot_into_metric_coordinates() -> None:
    attempt = _attempt()
    expected = CourtCoordinate(7.0, 0.0)
    attempts = MemoryAttempts([attempt])
    service = _service(
        attempts,
        calibrations=[_calibration(indicative=False)],
        observations={(attempt.id, "player-1"): _observation(expected)},
    )

    result = service.map_run("run-1")[0]

    assert result.source is LocationSource.CALIBRATED
    assert result.location is not None
    assert result.location.indicative is False
    assert result.location.court_x_m is not None
    assert abs(result.location.court_x_m - expected.x_m) < 1e-8
    assert result.location.court_y_m is not None
    assert abs(result.location.court_y_m - expected.y_m) < 1e-8
    assert result.shot_value is ShotValue.TWO_POINT
    assert attempts.locations[attempt.id] == result.location


def test_low_quality_or_non_standard_calibration_emits_indicative_coordinates() -> None:
    attempt = _attempt()
    attempts = MemoryAttempts([attempt])
    service = _service(
        attempts,
        calibrations=[_calibration(indicative=True)],
        observations={(attempt.id, "player-1"): _observation(CourtCoordinate(8.0, -3.0))},
    )

    result = service.map_run("run-1")[0]

    assert result.source is LocationSource.INDICATIVE
    assert result.location is not None
    assert result.location.indicative is True
    assert result.location.court_x_m is None
    assert result.location.court_y_m is None
    assert 0.0 <= result.location.normalized_x <= 1.0
    assert 0.0 <= result.location.normalized_y <= 1.0


def test_missing_shooter_or_observation_has_explicit_reason() -> None:
    missing_shooter = replace(_attempt(), shooter_track_id=None)
    no_observation = replace(_attempt(), id="attempt-2")
    attempts = MemoryAttempts([missing_shooter, no_observation])
    service = _service(attempts, calibrations=[], observations={})

    results = service.map_run("run-1")

    assert results[0].missing_reason is LocationMissingReason.NO_SHOOTER
    assert results[1].missing_reason is LocationMissingReason.NO_RELEASE_OBSERVATION
    assert attempts.locations == {}


def test_shooter_change_to_missing_geometry_clears_stale_location() -> None:
    attempt = _attempt()
    attempts = MemoryAttempts([attempt])
    attempts.locations[attempt.id] = ShotLocation(
        "old-location",
        attempt.id,
        5.0,
        0.0,
        0.4,
        0.5,
        "PAINT",
        False,
    )
    service = _service(attempts, calibrations=[], observations={})

    result = service.recalculate_after_shooter_change(attempt, None)

    assert result.missing_reason is LocationMissingReason.NO_SHOOTER
    assert attempts.locations == {}
    assert attempts.items[0].shot_type == "UNKNOWN"


def test_calibration_and_shooter_changes_recompute_persisted_location() -> None:
    attempt = _attempt()
    attempts = MemoryAttempts([attempt])
    calibrations = MemoryCalibrations([_calibration(indicative=True)])
    observations = MemoryObservations(
        {
            (attempt.id, "player-1"): _observation(CourtCoordinate(5.0, 0.0)),
            (attempt.id, "player-2"): _observation(CourtCoordinate(9.0, 7.0)),
        }
    )
    segments = MemorySegments([_segment()])
    service = CourtMappingService(segments, calibrations, attempts, observations)
    assert service.map_run("run-1")[0].source is LocationSource.INDICATIVE

    calibrations.items.append(_calibration(indicative=False, calibration_id="calibration-2"))
    service.request_recalculation(
        CalibrationRecalculationRequest(
            segment_id="segment-1",
            calibration_id="calibration-2",
            analysis_run_id="run-1",
            start_seconds=0.0,
            end_seconds=60.0,
            indicative_only=False,
            reason="CALIBRATION_CORRECTED",
        )
    )
    calibrated = attempts.locations[attempt.id]
    assert calibrated.indicative is False
    assert calibrated.court_x_m is not None and abs(calibrated.court_x_m - 5.0) < 1e-8

    changed = service.recalculate_after_shooter_change(attempt, "player-2")
    assert changed.location is not None
    assert changed.location.court_x_m is not None
    assert abs(changed.location.court_x_m - 9.0) < 1e-8
    assert changed.shot_value is ShotValue.THREE_POINT


def test_manual_location_recalculates_region_and_value_without_overwriting_evidence() -> None:
    attempts = MemoryAttempts([_attempt()])
    service = _service(attempts, calibrations=[], observations={})

    metric = service.recalculate_manual_location(
        "attempt-1",
        ManualLocation(court_coordinate=CourtCoordinate(0.0, -22.1 * FOOT_TO_METER)),
    )
    indicative = service.recalculate_manual_location(
        "attempt-1",
        ManualLocation(
            normalized_coordinate=NormalizedCourtCoordinate(0.8, 0.5),
            indicative=True,
        ),
    )

    assert metric.shot_value is ShotValue.THREE_POINT
    assert metric.location is not None
    assert metric.location.region == "LEFT_CORNER_THREE"
    assert indicative.location is not None
    assert indicative.location.indicative is True
    assert indicative.location.court_x_m is None
    assert attempts.locations == {}


def _service(
    attempts: MemoryAttempts,
    *,
    calibrations: Sequence[Calibration],
    observations: dict[tuple[str, str], ReleasePlayerObservation],
) -> CourtMappingService:
    return CourtMappingService(
        MemorySegments([_segment()]),
        MemoryCalibrations(calibrations),
        attempts,
        MemoryObservations(observations),
    )


def _segment() -> CameraSegment:
    return CameraSegment("segment-1", "run-1", 0.0, 60.0, "STABLE", 0.95)


def _attempt() -> ShotAttempt:
    return ShotAttempt(
        "attempt-1",
        "run-1",
        "player-1",
        20.0,
        ShotOutcome.MISSED,
        "UNKNOWN",
        0.8,
        ReviewStatus.UNREVIEWED,
        {"release_frame": 600},
    )


def _calibration(
    *,
    indicative: bool,
    calibration_id: str = "calibration-1",
) -> Calibration:
    assessment = CalibrationAssessment(
        CalibrationValidity.INDICATIVE if indicative else CalibrationValidity.PRECISE,
        0.95,
        (),
    )
    geometry = CalibrationGeometry(
        rim=RimGeometry(ImagePoint(320.0, 200.0), 20.0, 8.0, 0.95),
        court_points=tuple(
            CourtReferenceObservation(name, _image_from_court(court), 0.95)
            for name, court in (
                (
                    NBACourtReferencePoint.LEFT_BASELINE_CORNER,
                    CourtCoordinate(-4.0 * FOOT_TO_METER, -25.0 * FOOT_TO_METER),
                ),
                (
                    NBACourtReferencePoint.RIGHT_BASELINE_CORNER,
                    CourtCoordinate(-4.0 * FOOT_TO_METER, 25.0 * FOOT_TO_METER),
                ),
                (
                    NBACourtReferencePoint.RIGHT_FREE_THROW_LANE,
                    CourtCoordinate(15.0 * FOOT_TO_METER, 8.0 * FOOT_TO_METER),
                ),
                (
                    NBACourtReferencePoint.LEFT_FREE_THROW_LANE,
                    CourtCoordinate(15.0 * FOOT_TO_METER, -8.0 * FOOT_TO_METER),
                ),
                (NBACourtReferencePoint.FREE_THROW_CENTER, CourtCoordinate(15.0 * FOOT_TO_METER, 0.0)),
            )
        ),
        assessment=assessment,
    )
    return Calibration(
        calibration_id,
        "segment-1",
        "USER",
        geometry.rim_json(),
        geometry.court_points_json(),
        assessment.confidence,
        indicative,
        NOW,
    )


def _observation(court: CourtCoordinate) -> ReleasePlayerObservation:
    foot = _image_from_court(court)
    return ReleasePlayerObservation(
        bounding_box=ImageBoundingBox(foot.x - 20.0, foot.y - 160.0, foot.x + 20.0, foot.y),
        frame_width=640,
        frame_height=480,
    )


def _image_from_court(point: CourtCoordinate) -> ImagePoint:
    return ImagePoint(
        x=320.0 + 20.0 * point.y_m,
        y=420.0 - 20.0 * (point.x_m + 4.0 * FOOT_TO_METER),
    )
