"""Statistics, shot chart, heatmap, replay, and full-video view routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from shotsight2.api.deps import get_video_library_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/statistics", response_class=HTMLResponse)
def statistics_page(
    request: Request,
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render aggregate statistics, shot chart, heatmap, and artifact links."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return jinja_templates.TemplateResponse(
        request,
        "statistics.html",
        {
            "locale": locale,
            "video_id": video_id,
            "stats": detail.card.statistics,
            "artifacts": list(detail.artifacts),
            "error": None,
            "success": None,
        },
    )
