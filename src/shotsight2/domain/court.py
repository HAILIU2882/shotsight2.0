"""NBA court geometry, shot regions, and chart coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import hypot, isfinite, sqrt

from shotsight2.domain.calibration import FOOT_TO_METER, CourtCoordinate

NBA_COURT_LENGTH_M = 94.0 * FOOT_TO_METER
NBA_COURT_WIDTH_M = 50.0 * FOOT_TO_METER
NBA_HALF_COURT_LENGTH_M = NBA_COURT_LENGTH_M / 2.0
NBA_BASELINE_X_M = -4.0 * FOOT_TO_METER
NBA_HALF_COURT_X_M = 43.0 * FOOT_TO_METER
NBA_OPPOSITE_BASELINE_X_M = 90.0 * FOOT_TO_METER
NBA_SIDELINE_Y_M = 25.0 * FOOT_TO_METER
NBA_PAINT_END_X_M = 15.0 * FOOT_TO_METER
NBA_PAINT_HALF_WIDTH_M = 8.0 * FOOT_TO_METER
NBA_RESTRICTED_AREA_RADIUS_M = 4.0 * FOOT_TO_METER
NBA_CORNER_THREE_Y_M = 22.0 * FOOT_TO_METER
NBA_THREE_POINT_RADIUS_M = 23.75 * FOOT_TO_METER
NBA_CORNER_ARC_INTERSECTION_X_M = sqrt(NBA_THREE_POINT_RADIUS_M**2 - NBA_CORNER_THREE_Y_M**2)


class ShotValue(StrEnum):
    """Point value determined solely from stored court geometry."""

    TWO_POINT = "TWO_POINT"
    THREE_POINT = "THREE_POINT"


class CourtRegion(StrEnum):
    """Stable named regions used by charts, filters, and summaries."""

    RESTRICTED_AREA = "RESTRICTED_AREA"
    PAINT = "PAINT"
    LEFT_SHORT_MIDRANGE = "LEFT_SHORT_MIDRANGE"
    RIGHT_SHORT_MIDRANGE = "RIGHT_SHORT_MIDRANGE"
    CENTER_MIDRANGE = "CENTER_MIDRANGE"
    LEFT_CORNER_THREE = "LEFT_CORNER_THREE"
    RIGHT_CORNER_THREE = "RIGHT_CORNER_THREE"
    LEFT_WING_THREE = "LEFT_WING_THREE"
    RIGHT_WING_THREE = "RIGHT_WING_THREE"
    CENTER_THREE = "CENTER_THREE"
    BACKCOURT = "BACKCOURT"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"


@dataclass(frozen=True, slots=True)
class NormalizedCourtCoordinate:
    """Chart point normalized over one offensive NBA half court."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError("Normalized court coordinates must be finite")
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("Normalized court coordinates must be between zero and one")


@dataclass(frozen=True, slots=True)
class HeatmapBucket:
    """Deterministic rectangular heatmap bucket."""

    column: int
    row: int
    columns: int
    rows: int

    @property
    def key(self) -> str:
        """Return a stable serialization key."""
        return f"{self.column}:{self.row}"


def is_in_bounds(point: CourtCoordinate) -> bool:
    """Return whether a rim-centered metric point lies on the NBA court."""
    return (
        NBA_BASELINE_X_M <= point.x_m <= NBA_OPPOSITE_BASELINE_X_M
        and -NBA_SIDELINE_Y_M <= point.y_m <= NBA_SIDELINE_Y_M
    )


def shot_value(point: CourtCoordinate, *, tolerance_m: float = 1e-6) -> ShotValue:
    """Classify the NBA corner lines and circular three-point arc.

    A release foot touching either painted boundary is a two-point attempt.
    """
    lateral = abs(point.y_m)
    if lateral > NBA_CORNER_THREE_Y_M + tolerance_m and point.x_m <= (NBA_CORNER_ARC_INTERSECTION_X_M + tolerance_m):
        return ShotValue.THREE_POINT
    if hypot(point.x_m, point.y_m) > NBA_THREE_POINT_RADIUS_M + tolerance_m:
        return ShotValue.THREE_POINT
    return ShotValue.TWO_POINT


def court_region(point: CourtCoordinate) -> CourtRegion:
    """Return a named NBA region for one metric court point."""
    if not is_in_bounds(point):
        return CourtRegion.OUT_OF_BOUNDS
    if point.x_m > NBA_HALF_COURT_X_M:
        return CourtRegion.BACKCOURT

    value = shot_value(point)
    lateral = abs(point.y_m)
    distance = hypot(point.x_m, point.y_m)
    if value is ShotValue.THREE_POINT:
        if lateral > NBA_CORNER_THREE_Y_M and point.x_m <= NBA_CORNER_ARC_INTERSECTION_X_M:
            return CourtRegion.LEFT_CORNER_THREE if point.y_m < 0 else CourtRegion.RIGHT_CORNER_THREE
        if lateral <= 8.0 * FOOT_TO_METER:
            return CourtRegion.CENTER_THREE
        return CourtRegion.LEFT_WING_THREE if point.y_m < 0 else CourtRegion.RIGHT_WING_THREE

    if distance <= NBA_RESTRICTED_AREA_RADIUS_M and point.x_m >= NBA_BASELINE_X_M:
        return CourtRegion.RESTRICTED_AREA
    if point.x_m <= NBA_PAINT_END_X_M and lateral <= NBA_PAINT_HALF_WIDTH_M:
        return CourtRegion.PAINT
    if lateral <= 8.0 * FOOT_TO_METER:
        return CourtRegion.CENTER_MIDRANGE
    return CourtRegion.LEFT_SHORT_MIDRANGE if point.y_m < 0 else CourtRegion.RIGHT_SHORT_MIDRANGE


def normalize_court_coordinate(point: CourtCoordinate, *, clamp: bool = True) -> NormalizedCourtCoordinate:
    """Normalize a rim-centered metric point over the offensive half court."""
    x = (point.x_m - NBA_BASELINE_X_M) / NBA_HALF_COURT_LENGTH_M
    y = (point.y_m + NBA_SIDELINE_Y_M) / NBA_COURT_WIDTH_M
    if clamp:
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
    return NormalizedCourtCoordinate(x, y)


def denormalize_court_coordinate(point: NormalizedCourtCoordinate) -> CourtCoordinate:
    """Convert a normalized chart point into the canonical NBA court model."""
    return CourtCoordinate(
        x_m=NBA_BASELINE_X_M + point.x * NBA_HALF_COURT_LENGTH_M,
        y_m=-NBA_SIDELINE_Y_M + point.y * NBA_COURT_WIDTH_M,
    )


def heatmap_bucket(
    point: NormalizedCourtCoordinate,
    *,
    columns: int = 12,
    rows: int = 10,
) -> HeatmapBucket:
    """Assign a normalized chart point to a stable rectangular bucket."""
    if columns <= 0 or rows <= 0:
        raise ValueError("Heatmap dimensions must be positive")
    column = min(columns - 1, int(point.x * columns))
    row = min(rows - 1, int(point.y * rows))
    return HeatmapBucket(column, row, columns, rows)
