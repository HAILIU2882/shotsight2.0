"""Calibration review and correction routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_calibration_service
from shotsight2.domain.calibration import ImagePoint, RimGeometry
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.calibration import CalibrationService, CorrectCalibrationCommand

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/calibration", response_class=HTMLResponse)
def calibration_page(
    request: Request,
    video_id: str,
    calibration: Annotated[CalibrationService, Depends(get_calibration_service)],
    locale: Annotated[str, Depends(locale_param)],
    run_id: str = Query(default=""),
) -> HTMLResponse:
    """Show calibration data for all segments in a run."""
    segments = calibration.presentation_models_for_run(run_id) if run_id else ()
    return jinja_templates.TemplateResponse(
        request,
        "calibration.html",
        {
            "locale": locale,
            "video_id": video_id,
            "run_id": run_id,
            "segments": list(segments),
            "error": None,
            "success": None,
        },
    )


@router.post("/videos/{video_id}/segments/{segment_id}/calibration", response_class=HTMLResponse, response_model=None)
def correct_calibration(
    request: Request,
    video_id: str,
    segment_id: str,
    calibration: Annotated[CalibrationService, Depends(get_calibration_service)],
    locale: Annotated[str, Depends(locale_param)],
    run_id: Annotated[str, Form()] = "",
    rim_center_x: Annotated[float | None, Form()] = None,
    rim_center_y: Annotated[float | None, Form()] = None,
    rim_radius_x: Annotated[float | None, Form()] = None,
    rim_radius_y: Annotated[float | None, Form()] = None,
    indicative_only: Annotated[str, Form()] = "",
) -> Response:
    """Apply a calibration correction submitted from the form."""
    rim: RimGeometry | None = None
    if all(v is not None for v in [rim_center_x, rim_center_y, rim_radius_x, rim_radius_y]):
        rim = RimGeometry(
            center=ImagePoint(x=rim_center_x, y=rim_center_y),  # type: ignore[arg-type]
            radius_x=rim_radius_x,  # type: ignore[arg-type]
            radius_y=rim_radius_y,  # type: ignore[arg-type]
            confidence=1.0,
        )
    command = CorrectCalibrationCommand(
        segment_id=segment_id,
        rim=rim,
        court_points={},
        indicative_only=indicative_only == "true",
    )
    calibration.correct_segment(command)
    return RedirectResponse(
        url=f"/videos/{video_id}/calibration?run_id={run_id}&locale={locale}",
        status_code=303,
    )
