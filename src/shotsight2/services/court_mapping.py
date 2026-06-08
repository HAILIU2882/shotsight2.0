"""Map shooter release observations into calibrated or indicative court locations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from shotsight2.domain import Calibration, CameraSegment, ShotAttempt, ShotLocation
from shotsight2.domain.calibration import (
    NBA_COURT_REFERENCE_COORDINATES,
    CalibrationValidity,
    CourtCoordinate,
    calibration_geometry_from_json,
)
from shotsight2.domain.court import (
    NormalizedCourtCoordinate,
    ShotValue,
    court_region,
    denormalize_court_coordinate,
    heatmap_bucket,
    normalize_court_coordinate,
    shot_value,
)
from shotsight2.domain.homography import Homography, HomographyValidation, solve_homography, validate_homography
from shotsight2.domain.release_position import (
    ReleasePlayerObservation,
    estimate_release_foot_position,
    indicative_coordinate,
)
from shotsight2.ports.repositories import (
    CalibrationRepository,
    CameraSegmentRepository,
    CourtMappingAttemptRepository,
)
from shotsight2.services.calibration import CalibrationRecalculationRequest


class LocationMissingReason(StrEnum):
    """Reason a shot cannot receive even an indicative chart point."""

    NO_STABLE_SEGMENT = "NO_STABLE_SEGMENT"
    NO_SHOOTER = "NO_SHOOTER"
    NO_RELEASE_OBSERVATION = "NO_RELEASE_OBSERVATION"


class LocationSource(StrEnum):
    """Geometry source used to produce a shot location."""

    CALIBRATED = "CALIBRATED"
    INDICATIVE = "INDICATIVE"
    MANUAL = "MANUAL"


@dataclass(frozen=True, slots=True)
class MappingResult:
    """Location mapping outcome with explicit failure and quality metadata."""

    attempt_id: str
    location: ShotLocation | None
    shot_value: ShotValue | None
    source: LocationSource | None
    heatmap_bucket_key: str | None
    missing_reason: LocationMissingReason | None = None
    homography_validation: HomographyValidation | None = None

    def __post_init__(self) -> None:
        if (self.location is None) == (self.missing_reason is None):
            raise ValueError("Mapping result must contain either a location or a missing reason")


@dataclass(frozen=True, slots=True)
class ManualLocation:
    """Correction geometry supplied by a future review application service."""

    court_coordinate: CourtCoordinate | None = None
    normalized_coordinate: NormalizedCourtCoordinate | None = None
    indicative: bool = False

    def __post_init__(self) -> None:
        if (self.court_coordinate is None) == (self.normalized_coordinate is None):
            raise ValueError("Manual location requires exactly one coordinate representation")
        if not self.indicative and self.court_coordinate is None:
            raise ValueError("Metric manual locations require a court coordinate")


class ReleaseObservationProvider(Protocol):
    """Read player geometry at release without coupling to tracking storage."""

    def for_attempt(
        self,
        attempt: ShotAttempt,
        shooter_track_id: str,
    ) -> ReleasePlayerObservation | None: ...


class CourtMappingService:
    """Coordinate initial mapping and downstream location recalculation."""

    def __init__(
        self,
        segments: CameraSegmentRepository,
        calibrations: CalibrationRepository,
        attempts: CourtMappingAttemptRepository,
        observations: ReleaseObservationProvider,
    ) -> None:
        self._segments = segments
        self._calibrations = calibrations
        self._attempts = attempts
        self._observations = observations

    def map_run(self, run_id: str) -> tuple[MappingResult, ...]:
        """Map every attempt in a run and persist every usable location."""
        segments = tuple(
            segment for segment in self._segments.list_for_run(run_id) if segment.stability_status.upper() == "STABLE"
        )
        results = tuple(self._map_attempt(attempt, segments) for attempt in self._attempts.list_for_run(run_id))
        self._persist_available(results)
        return results

    def request_recalculation(self, request: CalibrationRecalculationRequest) -> None:
        """Implement the calibration module's downstream recalculation port."""
        segment = self._segments.get(request.segment_id)
        if segment is None:
            return
        results = tuple(
            self._map_attempt(attempt, (segment,))
            for attempt in self._attempts.list_for_run(request.analysis_run_id)
            if request.start_seconds <= attempt.release_seconds < request.end_seconds
        )
        self._persist_available(results)

    def recalculate_after_shooter_change(
        self,
        attempt: ShotAttempt,
        shooter_track_id: str | None,
    ) -> MappingResult:
        """Re-map one attempt using its corrected shooter identity."""
        segment = self._segment_for_attempt(attempt)
        if segment is None:
            result = _missing(attempt.id, LocationMissingReason.NO_STABLE_SEGMENT)
            self._persist_available((result,))
            return result
        if shooter_track_id is None:
            result = _missing(attempt.id, LocationMissingReason.NO_SHOOTER)
            self._persist_available((result,))
            return result
        result = self._map_attempt(attempt, (segment,), shooter_track_id=shooter_track_id)
        self._persist_available((result,))
        return result

    def recalculate_manual_location(
        self,
        attempt_id: str,
        correction: ManualLocation,
    ) -> MappingResult:
        """Recompute region and shot value for a manual location correction.

        The caller owns correction persistence; this method deliberately does
        not overwrite automatic model evidence.
        """
        if correction.court_coordinate is not None:
            court = correction.court_coordinate
            normalized = normalize_court_coordinate(court)
        else:
            assert correction.normalized_coordinate is not None
            normalized = correction.normalized_coordinate
            court = denormalize_court_coordinate(normalized)
        location = _location(
            attempt_id,
            court=None if correction.indicative else court,
            normalized=normalized,
            indicative=correction.indicative,
            region_court=court,
        )
        return _result(attempt_id, location, LocationSource.MANUAL, court)

    def _map_attempt(
        self,
        attempt: ShotAttempt,
        segments: Sequence[CameraSegment],
        *,
        shooter_track_id: str | None = None,
    ) -> MappingResult:
        segment = next(
            (
                candidate
                for candidate in segments
                if candidate.start_seconds <= attempt.release_seconds < candidate.end_seconds
            ),
            None,
        )
        if segment is None:
            return _missing(attempt.id, LocationMissingReason.NO_STABLE_SEGMENT)
        shooter_id = attempt.shooter_track_id if shooter_track_id is None else shooter_track_id
        if shooter_id is None:
            return _missing(attempt.id, LocationMissingReason.NO_SHOOTER)
        observation = self._observations.for_attempt(attempt, shooter_id)
        if observation is None:
            return _missing(attempt.id, LocationMissingReason.NO_RELEASE_OBSERVATION)

        calibration = self._calibrations.latest_for_segment(segment.id)
        homography, validation = _validated_homography(calibration)
        if homography is not None:
            court = homography.transform(estimate_release_foot_position(observation))
            location = _location(
                attempt.id,
                court=court,
                normalized=normalize_court_coordinate(court),
                indicative=False,
                region_court=court,
            )
            return _result(
                attempt.id,
                location,
                LocationSource.CALIBRATED,
                court,
                homography_validation=validation,
            )

        normalized = indicative_coordinate(observation)
        indicative_court = denormalize_court_coordinate(normalized)
        location = _location(
            attempt.id,
            court=None,
            normalized=normalized,
            indicative=True,
            region_court=indicative_court,
        )
        return _result(
            attempt.id,
            location,
            LocationSource.INDICATIVE,
            indicative_court,
            homography_validation=validation,
        )

    def _segment_for_attempt(self, attempt: ShotAttempt) -> CameraSegment | None:
        return next(
            (
                segment
                for segment in self._segments.list_for_run(attempt.analysis_run_id)
                if segment.stability_status.upper() == "STABLE"
                and segment.start_seconds <= attempt.release_seconds < segment.end_seconds
            ),
            None,
        )

    def _persist_available(self, results: Sequence[MappingResult]) -> None:
        for result in results:
            if result.location is not None and result.shot_value is not None:
                self._attempts.update_location_and_shot_type(
                    result.attempt_id,
                    result.location,
                    result.shot_value.value,
                )
            else:
                self._attempts.clear_location_and_shot_type(result.attempt_id, "UNKNOWN")


def _validated_homography(
    calibration: Calibration | None,
) -> tuple[Homography | None, HomographyValidation | None]:
    if calibration is None or calibration.indicative_only:
        return None, None
    geometry = calibration_geometry_from_json(calibration.rim_geometry, calibration.court_points)
    if geometry.assessment.validity is not CalibrationValidity.PRECISE:
        return None, None
    correspondences = tuple(
        (observation.point, NBA_COURT_REFERENCE_COORDINATES[observation.name]) for observation in geometry.court_points
    )
    try:
        homography = solve_homography(correspondences)
    except ValueError:
        return None, HomographyValidation(False, float("inf"), float("inf"), "UNSTABLE_HOMOGRAPHY")
    validation = validate_homography(homography, correspondences)
    return (homography if validation.valid else None), validation


def _location(
    attempt_id: str,
    *,
    court: CourtCoordinate | None,
    normalized: NormalizedCourtCoordinate,
    indicative: bool,
    region_court: CourtCoordinate,
) -> ShotLocation:
    return ShotLocation(
        id=str(uuid5(uuid5(NAMESPACE_URL, attempt_id), "court-location-v1")),
        shot_attempt_id=attempt_id,
        court_x_m=None if court is None else court.x_m,
        court_y_m=None if court is None else court.y_m,
        normalized_x=normalized.x,
        normalized_y=normalized.y,
        region=court_region(region_court).value,
        indicative=indicative,
    )


def _result(
    attempt_id: str,
    location: ShotLocation,
    source: LocationSource,
    classification_point: CourtCoordinate,
    *,
    homography_validation: HomographyValidation | None = None,
) -> MappingResult:
    normalized = NormalizedCourtCoordinate(location.normalized_x, location.normalized_y)
    return MappingResult(
        attempt_id=attempt_id,
        location=location,
        shot_value=shot_value(classification_point),
        source=source,
        heatmap_bucket_key=heatmap_bucket(normalized).key,
        homography_validation=homography_validation,
    )


def _missing(attempt_id: str, reason: LocationMissingReason) -> MappingResult:
    return MappingResult(
        attempt_id=attempt_id,
        location=None,
        shot_value=None,
        source=None,
        heatmap_bucket_key=None,
        missing_reason=reason,
    )
