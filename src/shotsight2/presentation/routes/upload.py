"""Upload form page and form-submit handler."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_video_ingestion_service
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.video_ingestion import UploadVideoCommand, VideoIngestionError, VideoIngestionService

router = APIRouter(tags=["presentation"])


@router.get("/upload", response_class=HTMLResponse)
def upload_page(
    request: Request,
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render the upload form."""
    return jinja_templates.TemplateResponse(
        request, "upload.html", {"locale": locale, "form_error": None, "error": None, "success": None}
    )


@router.post("/upload", response_class=HTMLResponse, response_model=None)
async def upload_submit(
    request: Request,
    file: UploadFile,
    ingestion: Annotated[VideoIngestionService, Depends(get_video_ingestion_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> Response:
    """Process uploaded video file."""
    filename = file.filename or "upload"
    command = UploadVideoCommand(
        filename=filename,
        chunks=iter([await file.read()]),
        received_at=datetime.now(UTC),
    )
    try:
        result = ingestion.ingest(command)
    except VideoIngestionError as exc:
        return jinja_templates.TemplateResponse(
            request,
            "upload.html",
            {"locale": locale, "form_error": str(exc), "error": None, "success": None},
            status_code=422,
        )
    return RedirectResponse(
        url=f"/videos/{result.video.id}?locale={locale}",
        status_code=303,
    )
