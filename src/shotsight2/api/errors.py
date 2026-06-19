"""Shared error response model and domain-to-HTTP error mapping."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shotsight2.services.analysis_jobs import (
    ActiveAnalysisJobError,
    AnalysisJobNotFoundError,
    AnalysisRunNotFoundError,
    InvalidAnalysisJobTransitionError,
    VideoNotReadyError,
)
from shotsight2.services.deletion import ActiveVideoAnalysisError


class ErrorResponse(BaseModel):
    """Stable HTTP error envelope returned from every error path."""

    code: str
    message: str
    detail: Any = None


def _json_error(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(code=code, message=message, detail=detail).model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach domain error-to-HTTP exception handlers to a FastAPI application."""

    @app.exception_handler(ValueError)
    async def validation_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return _json_error(422, "VALIDATION_ERROR", str(exc))

    @app.exception_handler(VideoNotReadyError)
    async def video_not_ready_handler(request: Request, exc: VideoNotReadyError) -> JSONResponse:
        return _json_error(409, "VIDEO_NOT_READY", str(exc))

    @app.exception_handler(ActiveAnalysisJobError)
    async def active_job_handler(request: Request, exc: ActiveAnalysisJobError) -> JSONResponse:
        return _json_error(409, "ACTIVE_JOB_CONFLICT", str(exc))

    @app.exception_handler(AnalysisJobNotFoundError)
    async def job_not_found_handler(request: Request, exc: AnalysisJobNotFoundError) -> JSONResponse:
        return _json_error(404, "JOB_NOT_FOUND", str(exc))

    @app.exception_handler(AnalysisRunNotFoundError)
    async def run_not_found_handler(request: Request, exc: AnalysisRunNotFoundError) -> JSONResponse:
        return _json_error(404, "RUN_NOT_FOUND", str(exc))

    @app.exception_handler(InvalidAnalysisJobTransitionError)
    async def invalid_transition_handler(request: Request, exc: InvalidAnalysisJobTransitionError) -> JSONResponse:
        return _json_error(409, "INVALID_JOB_TRANSITION", str(exc))

    @app.exception_handler(ActiveVideoAnalysisError)
    async def deletion_active_job_handler(request: Request, exc: ActiveVideoAnalysisError) -> JSONResponse:
        return _json_error(409, "ACTIVE_JOB_CONFLICT", str(exc))
