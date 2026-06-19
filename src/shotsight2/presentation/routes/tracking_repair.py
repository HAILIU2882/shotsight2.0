"""Tracking-repair prompt submission route."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_tracking_service
from shotsight2.domain.tracking import (
    BoundingBox,
    ImagePoint,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingPrompt,
)
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.tracking import TrackingOrchestrator

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/tracking-repair", response_class=HTMLResponse)
def tracking_repair_page(
    request: Request,
    video_id: str,
    locale: Annotated[str, Depends(locale_param)],
    run_id: str = "",
) -> HTMLResponse:
    """Show the tracking-repair prompt form."""
    return jinja_templates.TemplateResponse(
        request,
        "tracking_repair.html",
        {"locale": locale, "video_id": video_id, "run_id": run_id, "error": None, "success": None},
    )


@router.post("/videos/{video_id}/tracking/submit", response_class=HTMLResponse, response_model=None)
def submit_tracking_prompt(
    request: Request,
    video_id: str,
    tracking: Annotated[TrackingOrchestrator, Depends(get_tracking_service)],
    locale: Annotated[str, Depends(locale_param)],
    segment_id: Annotated[str, Form()],
    timestamp_seconds: Annotated[float, Form()],
    kind: Annotated[str, Form()],
    point_x: Annotated[float | None, Form()] = None,
    point_y: Annotated[float | None, Form()] = None,
    box_x: Annotated[float | None, Form()] = None,
    box_y: Annotated[float | None, Form()] = None,
    box_w: Annotated[float | None, Form()] = None,
    box_h: Annotated[float | None, Form()] = None,
) -> Response:
    """Process a point or box tracking-repair prompt from the form."""
    try:
        prompt_kind = PromptKind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    point: ImagePoint | None = None
    box: BoundingBox | None = None
    if prompt_kind is PromptKind.POINT:
        if point_x is None or point_y is None:
            raise HTTPException(status_code=422, detail="Point coordinates required")
        point = ImagePoint(x=point_x, y=point_y)
    elif prompt_kind is PromptKind.BOX:
        if any(v is None for v in [box_x, box_y, box_w, box_h]):
            raise HTTPException(status_code=422, detail="Box geometry required")
        box = BoundingBox(x=box_x, y=box_y, width=box_w, height=box_h)  # type: ignore[arg-type]

    prompt = TrackingPrompt(
        id=str(uuid4()),
        segment_id=segment_id,
        timestamp_seconds=timestamp_seconds,
        object_class=TrackedObjectClass.BASKETBALL,
        kind=prompt_kind,
        source=PromptSource.USER,
        point=point,
        box=box,
    )
    tracking.save_user_prompt(prompt)
    return RedirectResponse(
        url=f"/videos/{video_id}/tracking-repair?locale={locale}",
        status_code=303,
    )
