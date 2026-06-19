"""Video library root page."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from shotsight2.api.deps import get_video_library_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(tags=["presentation"])


@router.get("/", response_class=HTMLResponse)
def library_page(
    request: Request,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render the video library dashboard."""
    result = library.list_videos()
    return jinja_templates.TemplateResponse(
        request,
        "library.html",
        {"locale": locale, "videos": list(result.videos), "error": None, "success": None},
    )
