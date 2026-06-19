"""Camera-segment listing and calibration correction routes."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from shotsight2.api.deps import get_calibration_service
from shotsight2.domain.calibration import (
    ImagePoint,
    NBACourtReferencePoint,
    RimGeometry,
)
from shotsight2.services.calibration import CalibrationService, CorrectCalibrationCommand

router = APIRouter(prefix="/videos/{video_id}", tags=["segments"])


class ImagePointSchema(BaseModel):
    """Image-space pixel coordinate."""

    x: float
    y: float


class RimGeometrySchema(BaseModel):
    """Rim ellipse geometry in image-frame pixel coordinates."""

    center: ImagePointSchema
    radius_x: float
    radius_y: float
    confidence: float = 1.0


class CalibrationCorrectionRequest(BaseModel):
    """User-supplied calibration correction for one camera segment."""

    segment_id: str
    rim: RimGeometrySchema | None = None
    court_points: dict[str, ImagePointSchema] = {}
    indicative_only: bool = False


@router.get("/segments")
def list_segments(
    video_id: str,
    run_id: str,
    calibration: Annotated[CalibrationService, Depends(get_calibration_service)],
) -> list[dict[str, Any]]:
    """Return all calibration presentation models for a specific analysis run."""
    models = calibration.presentation_models_for_run(run_id)
    return [dataclasses.asdict(m) for m in models]


@router.patch("/segments/{segment_id}/calibration")
def correct_calibration(
    video_id: str,
    segment_id: str,
    body: CalibrationCorrectionRequest,
    calibration: Annotated[CalibrationService, Depends(get_calibration_service)],
) -> dict[str, Any]:
    """Apply a user calibration correction to a camera segment.

    Returns the updated Calibration record.
    Raises 422 on validation errors (invalid geometry, blank segment ID).
    """
    if body.segment_id != segment_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Segment ID in body must match path")

    rim: RimGeometry | None = None
    if body.rim is not None:
        rim = RimGeometry(
            center=ImagePoint(x=body.rim.center.x, y=body.rim.center.y),
            radius_x=body.rim.radius_x,
            radius_y=body.rim.radius_y,
            confidence=body.rim.confidence,
        )

    court_points: dict[NBACourtReferencePoint, ImagePoint] = {}
    for key_str, pt in body.court_points.items():
        try:
            ref = NBACourtReferencePoint(key_str)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail=f"Unknown court reference point: {key_str!r}") from exc
        court_points[ref] = ImagePoint(x=pt.x, y=pt.y)

    command = CorrectCalibrationCommand(
        segment_id=segment_id,
        rim=rim,
        court_points=court_points,
        indicative_only=body.indicative_only,
    )
    calibration_record = calibration.correct_segment(command)
    return dataclasses.asdict(calibration_record)
