"""Tracking repair prompt submission route."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from shotsight2.api.deps import get_tracking_repair_service
from shotsight2.domain.tracking import (
    PromptKind,
    TrackedObjectClass,
)
from shotsight2.services.tracking_repair import (
    TrackingRepairNotFoundError,
    TrackingRepairService,
    TrackingRepairUnavailableError,
)

router = APIRouter(prefix="/videos/{video_id}", tags=["tracking"])


class BoundingBoxSchema(BaseModel):
    """Axis-aligned bounding box in pixel coordinates."""

    x: float
    y: float
    width: float
    height: float


class TrackingPromptRequest(BaseModel):
    """Request body for submitting a user tracking repair prompt."""

    segment_id: str
    timestamp_seconds: float
    object_class: str
    kind: str
    point: dict[str, float] | None = None
    box: BoundingBoxSchema | None = None

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, v: str) -> str:
        try:
            k = PromptKind(v)
        except ValueError:
            raise ValueError(f"Unknown prompt kind: {v!r}") from None
        if k not in {PromptKind.POINT, PromptKind.BOX}:
            raise ValueError(f"Unsupported prompt kind for repair: {v!r}")
        return v

    @field_validator("object_class")
    @classmethod
    def _valid_class(cls, v: str) -> str:
        try:
            TrackedObjectClass(v)
        except ValueError:
            raise ValueError(f"Unknown object class: {v!r}") from None
        return v


@router.post("/tracking/prompts", status_code=409)
def submit_tracking_prompt(
    video_id: str,
    body: TrackingPromptRequest,
    repair: Annotated[TrackingRepairService, Depends(get_tracking_repair_service)],
) -> dict[str, Any]:
    """Reject repair prompts until completed-run application is supported.

    Raises 422 for unknown object classes, unsupported prompt kinds, or missing geometry.
    """
    kind = PromptKind(body.kind)
    if kind is PromptKind.POINT:
        if body.point is None:
            raise HTTPException(status_code=422, detail="Point geometry required for POINT prompt")
    elif kind is PromptKind.BOX:
        if body.box is None:
            raise HTTPException(status_code=422, detail="Box geometry required for BOX prompt")
    try:
        repair.reject_submission(video_id, body.segment_id)
    except TrackingRepairNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrackingRepairUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise AssertionError("Tracking repair unexpectedly accepted a submission")
