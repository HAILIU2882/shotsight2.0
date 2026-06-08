"""Dependency-free projective transform solving and validation."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite

from shotsight2.domain.calibration import CourtCoordinate, ImagePoint


@dataclass(frozen=True, slots=True)
class Homography:
    """Three-by-three image-to-court projective transform."""

    values: tuple[float, float, float, float, float, float, float, float, float]

    def __post_init__(self) -> None:
        if len(self.values) != 9 or not all(isfinite(value) for value in self.values):
            raise ValueError("Homography must contain nine finite values")

    def transform(self, point: ImagePoint) -> CourtCoordinate:
        """Project one image point into court meters."""
        a, b, c, d, e, f, g, h, i = self.values
        denominator = g * point.x + h * point.y + i
        if abs(denominator) < 1e-10:
            raise ValueError("Image point projects to infinity")
        return CourtCoordinate(
            (a * point.x + b * point.y + c) / denominator,
            (d * point.x + e * point.y + f) / denominator,
        )


@dataclass(frozen=True, slots=True)
class HomographyValidation:
    """Validation metrics for a solved transform."""

    valid: bool
    root_mean_square_error_m: float
    maximum_error_m: float
    reason: str | None = None


def solve_homography(
    correspondences: tuple[tuple[ImagePoint, CourtCoordinate], ...],
) -> Homography:
    """Solve an image-to-court homography from four or more correspondences."""
    if len(correspondences) < 4:
        raise ValueError("At least four point correspondences are required")

    design: list[list[float]] = []
    targets: list[float] = []
    for image, court in correspondences:
        x, y = image.x, image.y
        u, v = court.x_m, court.y_m
        design.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        targets.append(u)
        design.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        targets.append(v)

    normal = [[0.0 for _ in range(8)] for _ in range(8)]
    rhs = [0.0 for _ in range(8)]
    for row, target in zip(design, targets, strict=True):
        for column in range(8):
            rhs[column] += row[column] * target
            for other in range(8):
                normal[column][other] += row[column] * row[other]
    solution = _solve_linear_system(normal, rhs)
    return Homography(
        (
            solution[0],
            solution[1],
            solution[2],
            solution[3],
            solution[4],
            solution[5],
            solution[6],
            solution[7],
            1.0,
        )
    )


def validate_homography(
    homography: Homography,
    correspondences: tuple[tuple[ImagePoint, CourtCoordinate], ...],
    *,
    maximum_rmse_m: float = 0.35,
    maximum_point_error_m: float = 0.75,
) -> HomographyValidation:
    """Validate reprojection error and reject singular projections."""
    if len(correspondences) < 4:
        return HomographyValidation(False, float("inf"), float("inf"), "INSUFFICIENT_REFERENCE_POINTS")
    errors: list[float] = []
    try:
        for image, expected in correspondences:
            actual = homography.transform(image)
            errors.append(hypot(actual.x_m - expected.x_m, actual.y_m - expected.y_m))
    except ValueError:
        return HomographyValidation(False, float("inf"), float("inf"), "SINGULAR_PROJECTION")
    rmse = (sum(error * error for error in errors) / len(errors)) ** 0.5
    maximum = max(errors)
    if rmse > maximum_rmse_m:
        return HomographyValidation(False, rmse, maximum, "HIGH_REPROJECTION_ERROR")
    if maximum > maximum_point_error_m:
        return HomographyValidation(False, rmse, maximum, "REFERENCE_POINT_OUTLIER")
    return HomographyValidation(True, rmse, maximum)


def calibrated_location_error(
    predicted: tuple[CourtCoordinate, ...],
    ground_truth: tuple[CourtCoordinate, ...],
) -> HomographyValidation:
    """Evaluate calibrated locations against equal-length ground truth."""
    if not predicted or len(predicted) != len(ground_truth):
        raise ValueError("Predicted and ground-truth coordinates must be non-empty and equal length")
    errors = [
        hypot(actual.x_m - expected.x_m, actual.y_m - expected.y_m)
        for actual, expected in zip(predicted, ground_truth, strict=True)
    ]
    rmse = (sum(error * error for error in errors) / len(errors)) ** 0.5
    return HomographyValidation(True, rmse, max(errors))


def _solve_linear_system(matrix: list[list[float]], values: list[float]) -> tuple[float, ...]:
    size = len(values)
    augmented = [row[:] + [value] for row, value in zip(matrix, values, strict=True)]
    scale = max((abs(value) for row in matrix for value in row), default=1.0)
    epsilon = max(1e-12, scale * 1e-12)
    for pivot_index in range(size):
        pivot_row = max(range(pivot_index, size), key=lambda row: abs(augmented[row][pivot_index]))
        if abs(augmented[pivot_row][pivot_index]) <= epsilon:
            raise ValueError("Reference points do not define a stable homography")
        augmented[pivot_index], augmented[pivot_row] = augmented[pivot_row], augmented[pivot_index]
        pivot = augmented[pivot_index][pivot_index]
        augmented[pivot_index] = [value / pivot for value in augmented[pivot_index]]
        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            if factor == 0.0:
                continue
            augmented[row_index] = [
                current - factor * pivot_value
                for current, pivot_value in zip(
                    augmented[row_index],
                    augmented[pivot_index],
                    strict=True,
                )
            ]
    return tuple(augmented[index][-1] for index in range(size))
