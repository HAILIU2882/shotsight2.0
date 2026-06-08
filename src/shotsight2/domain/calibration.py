"""Typed calibration geometry and validation rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import hypot, isfinite

from shotsight2.domain.persistence import JsonObject, JsonValue

FOOT_TO_METER = 0.3048


class CalibrationSource(StrEnum):
    """Origin of a calibration version."""

    AUTOMATIC = "AUTOMATIC"
    USER = "USER"


class CalibrationValidity(StrEnum):
    """Whether calibration geometry may produce metric court coordinates."""

    PRECISE = "PRECISE"
    INDICATIVE = "INDICATIVE"
    INVALID = "INVALID"


class CalibrationUncertaintyReason(StrEnum):
    """Machine-readable reasons a calibration is not metrically reliable."""

    MISSING_RIM = "MISSING_RIM"
    LOW_RIM_CONFIDENCE = "LOW_RIM_CONFIDENCE"
    INCOMPLETE_COURT_POINTS = "INCOMPLETE_COURT_POINTS"
    LOW_COURT_CONFIDENCE = "LOW_COURT_CONFIDENCE"
    INVALID_POINT_GEOMETRY = "INVALID_POINT_GEOMETRY"
    INVALID_POINT_ORDER = "INVALID_POINT_ORDER"
    NON_STANDARD_COURT = "NON_STANDARD_COURT"


class NBACourtReferencePoint(StrEnum):
    """Named NBA half-court points accepted by calibration."""

    LEFT_BASELINE_CORNER = "left_baseline_corner"
    RIGHT_BASELINE_CORNER = "right_baseline_corner"
    LEFT_FREE_THROW_LANE = "left_free_throw_lane"
    RIGHT_FREE_THROW_LANE = "right_free_throw_lane"
    FREE_THROW_CENTER = "free_throw_center"
    LEFT_CORNER_THREE = "left_corner_three"
    RIGHT_CORNER_THREE = "right_corner_three"
    RIM_CENTER = "rim_center"


@dataclass(frozen=True, slots=True)
class CourtCoordinate:
    """Metric point in an NBA court model, measured from the target rim."""

    x_m: float
    y_m: float


NBA_COURT_REFERENCE_COORDINATES: dict[NBACourtReferencePoint, CourtCoordinate] = {
    NBACourtReferencePoint.LEFT_BASELINE_CORNER: CourtCoordinate(-4.0 * FOOT_TO_METER, -25.0 * FOOT_TO_METER),
    NBACourtReferencePoint.RIGHT_BASELINE_CORNER: CourtCoordinate(-4.0 * FOOT_TO_METER, 25.0 * FOOT_TO_METER),
    NBACourtReferencePoint.LEFT_FREE_THROW_LANE: CourtCoordinate(15.0 * FOOT_TO_METER, -8.0 * FOOT_TO_METER),
    NBACourtReferencePoint.RIGHT_FREE_THROW_LANE: CourtCoordinate(15.0 * FOOT_TO_METER, 8.0 * FOOT_TO_METER),
    NBACourtReferencePoint.FREE_THROW_CENTER: CourtCoordinate(15.0 * FOOT_TO_METER, 0.0),
    NBACourtReferencePoint.LEFT_CORNER_THREE: CourtCoordinate(10.0 * FOOT_TO_METER, -22.0 * FOOT_TO_METER),
    NBACourtReferencePoint.RIGHT_CORNER_THREE: CourtCoordinate(10.0 * FOOT_TO_METER, 22.0 * FOOT_TO_METER),
    NBACourtReferencePoint.RIM_CENTER: CourtCoordinate(0.0, 0.0),
}

REQUIRED_PRECISE_REFERENCE_POINTS: tuple[NBACourtReferencePoint, ...] = (
    NBACourtReferencePoint.LEFT_BASELINE_CORNER,
    NBACourtReferencePoint.RIGHT_BASELINE_CORNER,
    NBACourtReferencePoint.RIGHT_FREE_THROW_LANE,
    NBACourtReferencePoint.LEFT_FREE_THROW_LANE,
)


@dataclass(frozen=True, slots=True)
class ImagePoint:
    """A point in representative-frame pixel coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("Image point coordinates must be finite")

    def to_json(self) -> JsonObject:
        """Serialize for repository JSON storage."""
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_json(cls, value: JsonObject) -> ImagePoint:
        """Deserialize a point from repository JSON."""
        return cls(_required_float(value, "x"), _required_float(value, "y"))


@dataclass(frozen=True, slots=True)
class CourtReferenceObservation:
    """One observed court reference point on a representative frame."""

    name: NBACourtReferencePoint
    point: ImagePoint
    confidence: float

    def __post_init__(self) -> None:
        _validate_confidence(self.confidence)

    def to_json(self) -> JsonObject:
        """Serialize for repository JSON storage."""
        court_point = NBA_COURT_REFERENCE_COORDINATES[self.name]
        return {
            "image": self.point.to_json(),
            "court_m": {"x": court_point.x_m, "y": court_point.y_m},
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class RimGeometry:
    """Ellipse approximation of the rim in image coordinates."""

    center: ImagePoint
    radius_x: float
    radius_y: float
    confidence: float

    def __post_init__(self) -> None:
        if self.radius_x <= 0 or self.radius_y <= 0:
            raise ValueError("Rim radii must be positive")
        _validate_confidence(self.confidence)

    def to_json(self) -> JsonObject:
        """Serialize for repository JSON storage."""
        return {
            "type": "ellipse",
            "center": self.center.to_json(),
            "radius_x": self.radius_x,
            "radius_y": self.radius_y,
            "confidence": self.confidence,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> RimGeometry:
        """Deserialize rim geometry from repository JSON."""
        center = value.get("center")
        if not isinstance(center, dict):
            raise ValueError("Rim geometry is missing a center point")
        return cls(
            center=ImagePoint.from_json(center),
            radius_x=_required_float(value, "radius_x"),
            radius_y=_required_float(value, "radius_y"),
            confidence=_required_float(value, "confidence"),
        )


@dataclass(frozen=True, slots=True)
class CalibrationProposal:
    """Backend-neutral automatic calibration evidence for one segment."""

    segment_id: str
    rim_candidates: tuple[RimGeometry, ...] = ()
    court_points: tuple[CourtReferenceObservation, ...] = ()
    court_standard_matches_nba: bool = True


@dataclass(frozen=True, slots=True)
class CalibrationAssessment:
    """Validation result used before persisting calibration evidence."""

    validity: CalibrationValidity
    confidence: float
    reasons: tuple[CalibrationUncertaintyReason, ...]

    @property
    def indicative_only(self) -> bool:
        """Return whether metric court coordinates must be suppressed."""
        return self.validity is not CalibrationValidity.PRECISE


@dataclass(frozen=True, slots=True)
class CalibrationGeometry:
    """Typed active geometry for a calibration version."""

    rim: RimGeometry | None
    court_points: tuple[CourtReferenceObservation, ...]
    assessment: CalibrationAssessment

    def rim_json(self) -> JsonObject:
        """Serialize rim geometry, preserving missing-rim uncertainty."""
        if self.rim is None:
            return {"type": "missing", "valid": False}
        payload = self.rim.to_json()
        payload["valid"] = True
        return payload

    def court_points_json(self) -> JsonObject:
        """Serialize court references and validation metadata."""
        return {
            "standard": "NBA",
            "points": {point.name.value: point.to_json() for point in self.court_points},
            "required_points": [point.value for point in REQUIRED_PRECISE_REFERENCE_POINTS],
            "validity": self.assessment.validity.value,
            "confidence_reasons": [reason.value for reason in self.assessment.reasons],
        }


def select_rim_candidate(candidates: tuple[RimGeometry, ...]) -> RimGeometry | None:
    """Select the highest-confidence valid rim proposal."""
    return max(candidates, key=lambda item: (item.confidence, item.radius_x * item.radius_y), default=None)


def ingest_court_reference_proposals(
    observations: tuple[CourtReferenceObservation, ...],
) -> tuple[CourtReferenceObservation, ...]:
    """Keep the best observation for each known NBA reference point."""
    best: dict[NBACourtReferencePoint, CourtReferenceObservation] = {}
    for observation in observations:
        current = best.get(observation.name)
        if current is None or observation.confidence > current.confidence:
            best[observation.name] = observation
    return tuple(best[name] for name in sorted(best, key=lambda item: item.value))


def assess_calibration_geometry(
    rim: RimGeometry | None,
    court_points: tuple[CourtReferenceObservation, ...],
    *,
    court_standard_matches_nba: bool = True,
) -> CalibrationAssessment:
    """Validate geometry and compute a conservative calibration confidence."""
    reasons: list[CalibrationUncertaintyReason] = []
    if rim is None:
        reasons.append(CalibrationUncertaintyReason.MISSING_RIM)
        rim_confidence = 0.0
    else:
        rim_confidence = rim.confidence
        if rim.confidence < 0.55:
            reasons.append(CalibrationUncertaintyReason.LOW_RIM_CONFIDENCE)

    by_name = {point.name: point for point in court_points}
    missing_required = [name for name in REQUIRED_PRECISE_REFERENCE_POINTS if name not in by_name]
    if missing_required:
        reasons.append(CalibrationUncertaintyReason.INCOMPLETE_COURT_POINTS)

    if court_points:
        average_court_confidence = sum(point.confidence for point in court_points) / len(court_points)
        if average_court_confidence < 0.55:
            reasons.append(CalibrationUncertaintyReason.LOW_COURT_CONFIDENCE)
    else:
        average_court_confidence = 0.0

    if not court_standard_matches_nba:
        reasons.append(CalibrationUncertaintyReason.NON_STANDARD_COURT)

    required_geometry_valid = False
    if not missing_required:
        required_points = tuple(by_name[name].point for name in REQUIRED_PRECISE_REFERENCE_POINTS)
        required_geometry_valid = _has_homography_support(required_points)
        if not required_geometry_valid:
            reasons.append(CalibrationUncertaintyReason.INVALID_POINT_GEOMETRY)
        elif not _has_expected_order(required_points):
            reasons.append(CalibrationUncertaintyReason.INVALID_POINT_ORDER)

    precise = (
        rim is not None
        and not missing_required
        and required_geometry_valid
        and court_standard_matches_nba
        and not any(
            reason
            in {
                CalibrationUncertaintyReason.LOW_RIM_CONFIDENCE,
                CalibrationUncertaintyReason.LOW_COURT_CONFIDENCE,
                CalibrationUncertaintyReason.INVALID_POINT_ORDER,
            }
            for reason in reasons
        )
    )
    confidence = _bounded((rim_confidence + average_court_confidence) / 2)
    if missing_required or rim is None:
        confidence *= 0.45
    if not court_standard_matches_nba:
        confidence *= 0.5
    validity = CalibrationValidity.PRECISE if precise else CalibrationValidity.INDICATIVE
    return CalibrationAssessment(validity=validity, confidence=confidence, reasons=tuple(dict.fromkeys(reasons)))


def build_calibration_geometry(
    proposal: CalibrationProposal,
) -> CalibrationGeometry:
    """Create typed calibration geometry from automatic backend proposals."""
    rim = select_rim_candidate(proposal.rim_candidates)
    court_points = ingest_court_reference_proposals(proposal.court_points)
    assessment = assess_calibration_geometry(
        rim,
        court_points,
        court_standard_matches_nba=proposal.court_standard_matches_nba,
    )
    return CalibrationGeometry(rim=rim, court_points=court_points, assessment=assessment)


def calibration_geometry_from_json(
    rim_geometry: JsonObject,
    court_points: JsonObject,
) -> CalibrationGeometry:
    """Build typed geometry from persisted JSON."""
    rim_type = rim_geometry.get("type")
    rim = None if rim_type == "missing" else RimGeometry.from_json(rim_geometry)
    points_json = court_points.get("points")
    if not isinstance(points_json, dict):
        points_json = {}
    points: list[CourtReferenceObservation] = []
    for name_value, payload in points_json.items():
        if not isinstance(name_value, str) or not isinstance(payload, dict):
            continue
        try:
            name = NBACourtReferencePoint(name_value)
        except ValueError:
            continue
        image_value = payload.get("image")
        if not isinstance(image_value, dict):
            continue
        points.append(
            CourtReferenceObservation(
                name=name,
                point=ImagePoint.from_json(image_value),
                confidence=_required_float(payload, "confidence"),
            )
        )
    reason_values = court_points.get("confidence_reasons")
    reasons = (
        tuple(
            CalibrationUncertaintyReason(item)
            for item in reason_values
            if isinstance(item, str) and item in CalibrationUncertaintyReason
        )
        if isinstance(reason_values, list)
        else ()
    )
    validity_value = court_points.get("validity")
    validity = CalibrationValidity(validity_value) if isinstance(validity_value, str) else CalibrationValidity.INVALID
    confidence_values = [rim.confidence] if rim is not None else [0.0]
    confidence_values.extend(point.confidence for point in points)
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    return CalibrationGeometry(
        rim=rim,
        court_points=tuple(points),
        assessment=CalibrationAssessment(validity, _bounded(confidence), reasons),
    )


def _validate_confidence(value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError("Confidence must be between zero and one")


def _bounded(value: float) -> float:
    return min(1.0, max(0.0, value))


def _required_float(payload: JsonObject, key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"Expected numeric value for {key}")
    return float(value)


def _has_homography_support(points: tuple[ImagePoint, ...]) -> bool:
    unique = {(round(point.x, 6), round(point.y, 6)) for point in points}
    if len(unique) < 4:
        return False
    diagonal_a = hypot(points[0].x - points[2].x, points[0].y - points[2].y)
    diagonal_b = hypot(points[1].x - points[3].x, points[1].y - points[3].y)
    return abs(_polygon_area(points)) >= 1.0 and diagonal_a >= 1.0 and diagonal_b >= 1.0


def _has_expected_order(points: tuple[ImagePoint, ...]) -> bool:
    cross_signs = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        after_next = points[(index + 2) % len(points)]
        cross = (next_point.x - point.x) * (after_next.y - next_point.y) - (next_point.y - point.y) * (
            after_next.x - next_point.x
        )
        if abs(cross) > 1e-6:
            cross_signs.append(cross > 0)
    return bool(cross_signs) and all(sign is cross_signs[0] for sign in cross_signs)


def _polygon_area(points: tuple[ImagePoint, ...]) -> float:
    area = 0.0
    for point, next_point in zip(points, points[1:] + points[:1], strict=False):
        area += point.x * next_point.y - next_point.x * point.y
    return area / 2.0


def json_point(value: JsonValue) -> ImagePoint:
    """Parse an image point from API- or repository-shaped JSON."""
    if not isinstance(value, dict):
        raise ValueError("Point must be an object")
    return ImagePoint.from_json(value)
