"""Calibration application service and downstream recalculation contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from shotsight2.domain import Calibration, CameraSegment
from shotsight2.domain.calibration import (
    CalibrationAssessment,
    CalibrationGeometry,
    CalibrationProposal,
    CalibrationSource,
    CalibrationValidity,
    CourtReferenceObservation,
    ImagePoint,
    NBACourtReferencePoint,
    RimGeometry,
    assess_calibration_geometry,
    build_calibration_geometry,
    calibration_geometry_from_json,
)
from shotsight2.ports.repositories import CalibrationRepository, CameraSegmentRepository


class CalibrationValidationError(ValueError):
    """Raised when corrected geometry cannot be accepted."""


@dataclass(frozen=True, slots=True)
class CorrectCalibrationCommand:
    """User correction for one stable camera segment."""

    segment_id: str
    rim: RimGeometry | None
    court_points: Mapping[NBACourtReferencePoint, ImagePoint]
    indicative_only: bool = False
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CalibrationRecalculationRequest:
    """Contract emitted after a calibration correction affects shot locations."""

    segment_id: str
    calibration_id: str
    analysis_run_id: str
    start_seconds: float
    end_seconds: float
    indicative_only: bool
    reason: str


class LocationRecalculationTrigger(Protocol):
    """Port implemented later by court mapping/statistics orchestration."""

    def request_recalculation(self, request: CalibrationRecalculationRequest) -> None: ...


@dataclass(frozen=True, slots=True)
class PresentationCalibrationModel:
    """Route-neutral active calibration model for future UI/API adapters."""

    segment_id: str
    analysis_run_id: str
    start_seconds: float
    end_seconds: float
    representative_artifact_id: str | None
    active_calibration_id: str | None
    source: CalibrationSource | None
    rim: RimGeometry | None
    court_points: tuple[CourtReferenceObservation, ...]
    assessment: CalibrationAssessment
    indicative_only: bool


class CalibrationService:
    """Create automatic calibration versions and append post-analysis corrections."""

    def __init__(
        self,
        segments: CameraSegmentRepository,
        calibrations: CalibrationRepository,
        recalculation_trigger: LocationRecalculationTrigger | None = None,
    ) -> None:
        self._segments = segments
        self._calibrations = calibrations
        self._recalculation_trigger = recalculation_trigger

    def create_automatic_for_run(
        self,
        run_id: str,
        proposals: Sequence[CalibrationProposal],
        *,
        created_at: datetime | None = None,
    ) -> tuple[Calibration, ...]:
        """Persist automatic or indicative calibration for every stable segment."""
        proposal_by_segment = {proposal.segment_id: proposal for proposal in proposals}
        records: list[Calibration] = []
        for segment in self._stable_segments(run_id):
            proposal = proposal_by_segment.get(segment.id, CalibrationProposal(segment.id))
            geometry = build_calibration_geometry(proposal)
            calibration = _to_persistence_calibration(
                segment_id=segment.id,
                source=CalibrationSource.AUTOMATIC,
                geometry=geometry,
                created_at=created_at or datetime.now(UTC),
                calibration_id=_automatic_calibration_id(segment.id),
            )
            self._calibrations.add(calibration)
            records.append(calibration)
        return tuple(records)

    def correct_segment(self, command: CorrectCalibrationCommand) -> Calibration:
        """Validate and append a user calibration, then request location recalculation."""
        segment = self._find_segment(command.segment_id)
        observations = tuple(
            CourtReferenceObservation(name=name, point=point, confidence=1.0)
            for name, point in command.court_points.items()
        )
        assessment = assess_calibration_geometry(
            command.rim,
            observations,
            court_standard_matches_nba=not command.indicative_only,
        )
        if assessment.validity is not CalibrationValidity.PRECISE and not command.indicative_only:
            reason_text = ", ".join(reason.value for reason in assessment.reasons) or "INVALID_CALIBRATION"
            raise CalibrationValidationError(f"Calibration cannot produce precise coordinates: {reason_text}")
        geometry = CalibrationGeometry(
            rim=command.rim,
            court_points=observations,
            assessment=(
                assessment
                if not command.indicative_only
                else CalibrationAssessment(
                    CalibrationValidity.INDICATIVE,
                    assessment.confidence,
                    assessment.reasons,
                )
            ),
        )
        calibration = _to_persistence_calibration(
            segment_id=command.segment_id,
            source=CalibrationSource.USER,
            geometry=geometry,
            created_at=command.created_at or datetime.now(UTC),
            calibration_id=str(uuid4()),
        )
        self._calibrations.add(calibration)
        if self._recalculation_trigger is not None:
            self._recalculation_trigger.request_recalculation(
                CalibrationRecalculationRequest(
                    segment_id=segment.id,
                    calibration_id=calibration.id,
                    analysis_run_id=segment.analysis_run_id,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    indicative_only=calibration.indicative_only,
                    reason="CALIBRATION_CORRECTED",
                )
            )
        return calibration

    def presentation_models_for_run(self, run_id: str) -> tuple[PresentationCalibrationModel, ...]:
        """Return representative frame and active geometry for each stable segment."""
        return tuple(self._presentation_model(segment) for segment in self._stable_segments(run_id))

    def _presentation_model(self, segment: CameraSegment) -> PresentationCalibrationModel:
        calibration = self._calibrations.latest_for_segment(segment.id)
        if calibration is None:
            return PresentationCalibrationModel(
                segment_id=segment.id,
                analysis_run_id=segment.analysis_run_id,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                representative_artifact_id=segment.representative_artifact_id,
                active_calibration_id=None,
                source=None,
                rim=None,
                court_points=(),
                assessment=CalibrationAssessment(CalibrationValidity.INDICATIVE, 0.0, ()),
                indicative_only=True,
            )
        geometry = calibration_geometry_from_json(calibration.rim_geometry, calibration.court_points)
        return PresentationCalibrationModel(
            segment_id=segment.id,
            analysis_run_id=segment.analysis_run_id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            representative_artifact_id=segment.representative_artifact_id,
            active_calibration_id=calibration.id,
            source=CalibrationSource(calibration.source),
            rim=geometry.rim,
            court_points=geometry.court_points,
            assessment=geometry.assessment,
            indicative_only=calibration.indicative_only,
        )

    def _stable_segments(self, run_id: str) -> tuple[CameraSegment, ...]:
        return tuple(
            segment for segment in self._segments.list_for_run(run_id) if segment.stability_status.upper() == "STABLE"
        )

    def _find_segment(self, segment_id: str) -> CameraSegment:
        segment = self._segments.get(segment_id)
        if segment is None:
            raise CalibrationValidationError(f"Unknown camera segment: {segment_id}")
        if segment.stability_status.upper() != "STABLE":
            raise CalibrationValidationError("Only stable camera segments may be calibrated")
        return segment


def _to_persistence_calibration(
    *,
    segment_id: str,
    source: CalibrationSource,
    geometry: CalibrationGeometry,
    created_at: datetime,
    calibration_id: str,
) -> Calibration:
    return Calibration(
        id=calibration_id,
        segment_id=segment_id,
        source=source.value,
        rim_geometry=geometry.rim_json(),
        court_points=geometry.court_points_json(),
        confidence=geometry.assessment.confidence,
        indicative_only=geometry.assessment.indicative_only,
        created_at=created_at,
    )


def _automatic_calibration_id(segment_id: str) -> str:
    return str(uuid5(uuid5(NAMESPACE_URL, segment_id), "automatic-calibration-v1"))
