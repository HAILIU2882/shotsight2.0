"""Video detail, analyze, and reanalyze routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import (
    get_analysis_backend_configuration_service,
    get_analysis_job_service,
    get_video_library_service,
)
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.analysis_jobs import (
    AnalysisJobService,
    VideoNotReadyError,
)
from shotsight2.services.backend_configuration import AnalysisBackendConfigurationService
from shotsight2.services.tracking_backend_selection import BackendSelectionError
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail_page(
    request: Request,
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    backends: Annotated[
        AnalysisBackendConfigurationService,
        Depends(get_analysis_backend_configuration_service),
    ],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render the video detail page."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return jinja_templates.TemplateResponse(
        request,
        "video_detail.html",
        {
            "locale": locale,
            "detail": detail,
            "backend_catalog": backends.catalog(),
            "error": None,
            "success": None,
        },
    )


@router.post("/videos/{video_id}/analyze", response_class=HTMLResponse, response_model=None)
def start_analysis(
    request: Request,
    video_id: str,
    backend_name: Annotated[str, Form()],
    job_service: Annotated[AnalysisJobService, Depends(get_analysis_job_service)],
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    backends: Annotated[
        AnalysisBackendConfigurationService,
        Depends(get_analysis_backend_configuration_service),
    ],
    locale: Annotated[str, Depends(locale_param)],
) -> Response:
    """Start a new analysis run from the detail page form."""
    try:
        config = backends.resolve(backend_name)
        job_service.request_analysis(video_id, config)
    except (BackendSelectionError, VideoNotReadyError, ValueError) as exc:
        detail = library.get_video_detail(video_id)
        if detail is None:
            raise HTTPException(status_code=404) from exc
        return jinja_templates.TemplateResponse(
            request,
            "video_detail.html",
            {
                "locale": locale,
                "detail": detail,
                "backend_catalog": backends.catalog(),
                "error": str(exc),
                "success": None,
            },
            status_code=409,
        )
    return RedirectResponse(url=f"/videos/{video_id}?locale={locale}", status_code=303)


@router.post("/videos/{video_id}/reanalyze", response_class=HTMLResponse, response_model=None)
def reanalyze(
    request: Request,
    video_id: str,
    backend_name: Annotated[str, Form()],
    job_service: Annotated[AnalysisJobService, Depends(get_analysis_job_service)],
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
    backends: Annotated[
        AnalysisBackendConfigurationService,
        Depends(get_analysis_backend_configuration_service),
    ],
    locale: Annotated[str, Depends(locale_param)],
) -> Response:
    """Re-trigger analysis from the detail page."""
    try:
        config = backends.resolve(backend_name)
        job_service.request_reanalysis(video_id, config)
    except (BackendSelectionError, VideoNotReadyError, ValueError) as exc:
        detail = library.get_video_detail(video_id)
        if detail is None:
            raise HTTPException(status_code=404) from exc
        return jinja_templates.TemplateResponse(
            request,
            "video_detail.html",
            {
                "locale": locale,
                "detail": detail,
                "backend_catalog": backends.catalog(),
                "error": str(exc),
                "success": None,
            },
            status_code=409,
        )
    return RedirectResponse(url=f"/videos/{video_id}?locale={locale}", status_code=303)
