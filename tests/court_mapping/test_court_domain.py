"""NBA court geometry, homography, and release-position tests."""

from __future__ import annotations

from math import isclose

import pytest

from shotsight2.domain.calibration import FOOT_TO_METER, CourtCoordinate, ImagePoint
from shotsight2.domain.court import (
    NBA_CORNER_ARC_INTERSECTION_X_M,
    NBA_CORNER_THREE_Y_M,
    NBA_HALF_COURT_X_M,
    NBA_THREE_POINT_RADIUS_M,
    CourtRegion,
    NormalizedCourtCoordinate,
    ShotValue,
    court_region,
    heatmap_bucket,
    shot_value,
)
from shotsight2.domain.homography import (
    calibrated_location_error,
    solve_homography,
    validate_homography,
)
from shotsight2.domain.release_position import (
    ImageBoundingBox,
    ReleasePlayerObservation,
    estimate_release_foot_position,
    indicative_coordinate,
)


def test_nba_corner_and_arc_boundaries_require_feet_to_clear_the_line() -> None:
    """Both NBA boundary shapes classify reproducibly from metric geometry."""
    corner_boundary = CourtCoordinate(
        NBA_CORNER_ARC_INTERSECTION_X_M - 0.1,
        -NBA_CORNER_THREE_Y_M,
    )
    just_inside_corner = CourtCoordinate(
        NBA_CORNER_ARC_INTERSECTION_X_M - 0.1,
        -NBA_CORNER_THREE_Y_M + 0.01,
    )
    arc_boundary = CourtCoordinate(NBA_THREE_POINT_RADIUS_M, 0.0)
    beyond_corner = CourtCoordinate(
        NBA_CORNER_ARC_INTERSECTION_X_M - 0.1,
        -NBA_CORNER_THREE_Y_M - 0.01,
    )
    beyond_arc = CourtCoordinate(NBA_THREE_POINT_RADIUS_M + 0.01, 0.0)

    assert shot_value(corner_boundary) is ShotValue.TWO_POINT
    assert shot_value(just_inside_corner) is ShotValue.TWO_POINT
    assert shot_value(arc_boundary) is ShotValue.TWO_POINT
    assert shot_value(beyond_corner) is ShotValue.THREE_POINT
    assert court_region(beyond_corner) is CourtRegion.LEFT_CORNER_THREE
    assert shot_value(beyond_arc) is ShotValue.THREE_POINT
    assert court_region(beyond_arc) is CourtRegion.CENTER_THREE


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        (CourtCoordinate(2.0 * FOOT_TO_METER, 0.0), CourtRegion.RESTRICTED_AREA),
        (CourtCoordinate(10.0 * FOOT_TO_METER, 4.0 * FOOT_TO_METER), CourtRegion.PAINT),
        (CourtCoordinate(17.0 * FOOT_TO_METER, -10.0 * FOOT_TO_METER), CourtRegion.LEFT_SHORT_MIDRANGE),
        (CourtCoordinate(17.0 * FOOT_TO_METER, 10.0 * FOOT_TO_METER), CourtRegion.RIGHT_SHORT_MIDRANGE),
        (CourtCoordinate(18.0 * FOOT_TO_METER, 0.0), CourtRegion.CENTER_MIDRANGE),
        (CourtCoordinate(NBA_HALF_COURT_X_M + 0.01, 0.0), CourtRegion.BACKCOURT),
    ],
)
def test_named_regions_cover_paint_midrange_and_half_court(
    point: CourtCoordinate,
    expected: CourtRegion,
) -> None:
    assert court_region(point) is expected


def test_heatmap_bucket_is_stable_at_chart_edges() -> None:
    assert heatmap_bucket(NormalizedCourtCoordinate(0.0, 0.0)).key == "0:0"
    assert heatmap_bucket(NormalizedCourtCoordinate(1.0, 1.0)).key == "11:9"


def test_release_foot_prefers_ankles_and_falls_back_to_box_bottom() -> None:
    box = ImageBoundingBox(100.0, 50.0, 180.0, 250.0)
    with_ankles = ReleasePlayerObservation(
        box,
        640,
        480,
        left_ankle=ImagePoint(120.0, 242.0),
        right_ankle=ImagePoint(160.0, 246.0),
    )
    box_only = ReleasePlayerObservation(box, 640, 480)

    assert estimate_release_foot_position(with_ankles) == ImagePoint(140.0, 244.0)
    assert estimate_release_foot_position(box_only) == ImagePoint(140.0, 250.0)
    assert indicative_coordinate(box_only) == NormalizedCourtCoordinate(
        1.0 - 250.0 / 480.0,
        140.0 / 640.0,
    )


def test_homography_maps_synthetic_ground_truth_and_reports_error() -> None:
    correspondences = tuple(
        (_image_from_court(point), point)
        for point in (
            CourtCoordinate(-4.0 * FOOT_TO_METER, -25.0 * FOOT_TO_METER),
            CourtCoordinate(-4.0 * FOOT_TO_METER, 25.0 * FOOT_TO_METER),
            CourtCoordinate(15.0 * FOOT_TO_METER, 8.0 * FOOT_TO_METER),
            CourtCoordinate(15.0 * FOOT_TO_METER, -8.0 * FOOT_TO_METER),
            CourtCoordinate(15.0 * FOOT_TO_METER, 0.0),
        )
    )
    homography = solve_homography(correspondences)
    validation = validate_homography(homography, correspondences)
    expected = CourtCoordinate(7.0, -2.0)
    predicted = homography.transform(_image_from_court(expected))
    evaluation = calibrated_location_error((predicted,), (expected,))

    assert validation.valid is True
    assert validation.root_mean_square_error_m < 1e-8
    assert isclose(predicted.x_m, expected.x_m, abs_tol=1e-8)
    assert isclose(predicted.y_m, expected.y_m, abs_tol=1e-8)
    assert evaluation.maximum_error_m < 1e-8


def test_invalid_homography_geometry_is_rejected() -> None:
    repeated = tuple((ImagePoint(float(index), 10.0), CourtCoordinate(float(index), 0.0)) for index in range(4))
    with pytest.raises(ValueError, match="stable homography"):
        solve_homography(repeated)


def _image_from_court(point: CourtCoordinate) -> ImagePoint:
    return ImagePoint(
        x=320.0 + 20.0 * point.y_m,
        y=420.0 - 20.0 * (point.x_m + 4.0 * FOOT_TO_METER),
    )
