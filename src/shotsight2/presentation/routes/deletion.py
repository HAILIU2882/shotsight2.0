"""Deletion inventory and explicit destructive confirmation routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_deletion_service, get_video_library_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.deletion import VideoDeletionService
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/delete", response_class=HTMLResponse)
def deletion_page(
    request: Request,
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Show deletion inventory and destructive confirmation form."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return jinja_templates.TemplateResponse(
        request,
        "deletion.html",
        {
            "locale": locale,
            "video_id": video_id,
            "filename": detail.card.filename,
            "artifacts": list(detail.artifacts),
            "error": None,
            "success": None,
        },
    )


@router.post("/videos/{video_id}/confirm-delete", response_class=HTMLResponse, response_model=None)
def confirm_delete(
    request: Request,
    video_id: str,
    confirm_filename: Annotated[str, Form()],
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    deletion: Annotated[VideoDeletionService, Depends(get_deletion_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> Response:
    """Execute deletion only when the user has typed the exact filename."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404)
    if confirm_filename != detail.card.filename:
        return jinja_templates.TemplateResponse(
            request,
            "deletion.html",
            {
                "locale": locale,
                "video_id": video_id,
                "filename": detail.card.filename,
                "artifacts": list(detail.artifacts),
                "error": "Filename does not match. Deletion cancelled.",
                "success": None,
            },
            status_code=422,
        )
    deletion.delete_video(video_id)
    return RedirectResponse(url=f"/?locale={locale}", status_code=303)
