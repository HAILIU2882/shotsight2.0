"""Truthful, video-scoped tracking-repair presentation routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from shotsight2.api.deps import get_tracking_repair_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.tracking_repair import (
    TrackingRepairNotFoundError,
    TrackingRepairService,
    TrackingRepairUnavailableError,
)

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/tracking-repair", response_class=HTMLResponse)
def tracking_repair_page(
    request: Request,
    video_id: str,
    repair: Annotated[TrackingRepairService, Depends(get_tracking_repair_service)],
    locale: Annotated[str, Depends(locale_param)],
    run_id: str = "",
) -> HTMLResponse:
    """Show scoped segment evidence and explain why mutation is disabled."""
    try:
        context = repair.context(video_id, run_id or None)
    except TrackingRepairNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return jinja_templates.TemplateResponse(
        request,
        "tracking_repair.html",
        {"locale": locale, "video_id": video_id, "repair": context, "error": None},
    )


@router.post("/videos/{video_id}/tracking/submit", response_class=HTMLResponse, response_model=None)
def submit_tracking_prompt(
    request: Request,
    video_id: str,
    repair: Annotated[TrackingRepairService, Depends(get_tracking_repair_service)],
    locale: Annotated[str, Depends(locale_param)],
    segment_id: Annotated[str, Form()],
) -> Response:
    """Reject stale clients without accepting an ineffective repair prompt."""
    try:
        repair.reject_submission(video_id, segment_id)
    except TrackingRepairNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrackingRepairUnavailableError as exc:
        context = repair.context(video_id)
        return jinja_templates.TemplateResponse(
            request,
            "tracking_repair.html",
            {"locale": locale, "video_id": video_id, "repair": context, "error": str(exc)},
            status_code=409,
        )
    raise AssertionError("Tracking repair unexpectedly accepted a submission")
