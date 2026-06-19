"""Analysis start and job-progress routes."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from shotsight2.api.deps import get_analysis_job_service
from shotsight2.services.analysis_jobs import AnalysisConfiguration, AnalysisJobService

router = APIRouter(tags=["analysis"])


class StartAnalysisRequest(BaseModel):
    """Request body for starting a new analysis run."""

    backend_name: str
    backend_version: str
    values: dict[str, Any] = {}

    @field_validator("backend_name", "backend_version")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be blank")
        return v


@router.post("/videos/{video_id}/analysis", status_code=202)
def start_analysis(
    video_id: str,
    body: StartAnalysisRequest,
    job_service: Annotated[AnalysisJobService, Depends(get_analysis_job_service)],
) -> dict[str, Any]:
    """Start a new analysis run for a ready video.

    Returns 202 with the created job snapshot.
    Returns 409 on active-job conflict or non-ready video.
    """
    config = AnalysisConfiguration(
        backend_name=body.backend_name,
        backend_version=body.backend_version,
        values=body.values,
    )
    snapshot = job_service.request_analysis(video_id, config)
    return dataclasses.asdict(snapshot)


@router.get("/videos/{video_id}/analysis")
def get_analysis_status(
    video_id: str,
    job_service: Annotated[AnalysisJobService, Depends(get_analysis_job_service)],
) -> dict[str, Any]:
    """Return the current active job for a video, or an IDLE state when no job is active."""
    current = job_service.current_job()
    if current is not None and current.job.video_id == video_id:
        return dataclasses.asdict(current)
    return {"state": "IDLE", "video_id": video_id}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    job_service: Annotated[AnalysisJobService, Depends(get_analysis_job_service)],
) -> dict[str, Any]:
    """Return the active job matching job_id, or 404 when not found or not active.

    This endpoint serves progress polling; completed job history requires the
    video detail route.
    """
    current = job_service.current_job()
    if current is not None and current.job.id == job_id:
        return dataclasses.asdict(current)
    raise HTTPException(status_code=404, detail=f"Active job {job_id!r} not found")
