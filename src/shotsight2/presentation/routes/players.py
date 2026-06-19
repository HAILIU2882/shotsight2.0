"""Player list and rename routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_review_service, get_video_library_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.review import ReviewService
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/players", response_class=HTMLResponse)
def players_page(
    request: Request,
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render the player list for a video."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return jinja_templates.TemplateResponse(
        request,
        "players.html",
        {"locale": locale, "video_id": video_id, "players": list(detail.players), "error": None, "success": None},
    )


@router.post("/videos/{video_id}/players/{player_track_id}", response_class=HTMLResponse, response_model=None)
def rename_player(
    request: Request,
    video_id: str,
    player_track_id: str,
    display_name: Annotated[str, Form()],
    review: Annotated[ReviewService, Depends(get_review_service)],
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> Response:
    """Rename a player and redirect back to the players page."""
    if not display_name.strip():
        detail = library.get_video_detail(video_id)
        players = list(detail.players) if detail else []
        return jinja_templates.TemplateResponse(
            request,
            "players.html",
            {
                "locale": locale,
                "video_id": video_id,
                "players": players,
                "error": "Display name must not be blank",
                "success": None,
            },
            status_code=422,
        )
    review.rename_player(player_track_id, display_name.strip())
    return RedirectResponse(url=f"/videos/{video_id}/players?locale={locale}", status_code=303)
