"""Tracking repair prompt submission route."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from shotsight2.api.deps import get_tracking_service
from shotsight2.domain.tracking import (
    BoundingBox,
    ImagePoint,
    PromptKind,
    PromptSource,
    TrackedObjectClass,
    TrackingPrompt,
)
from shotsight2.services.tracking import TrackingOrchestrator

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


@router.post("/tracking/prompts", status_code=201)
def submit_tracking_prompt(
    video_id: str,
    body: TrackingPromptRequest,
    tracking: Annotated[TrackingOrchestrator, Depends(get_tracking_service)],
) -> dict[str, Any]:
    """Submit a user tracking-repair point or box prompt for full reanalysis.

    Raises 422 for unknown object classes, unsupported prompt kinds, or missing geometry.
    """
    kind = PromptKind(body.kind)
    point: ImagePoint | None = None
    box: BoundingBox | None = None
    if kind is PromptKind.POINT:
        if body.point is None:
            raise HTTPException(status_code=422, detail="Point geometry required for POINT prompt")
        point = ImagePoint(x=body.point["x"], y=body.point["y"])
    elif kind is PromptKind.BOX:
        if body.box is None:
            raise HTTPException(status_code=422, detail="Box geometry required for BOX prompt")
        box = BoundingBox(x=body.box.x, y=body.box.y, width=body.box.width, height=body.box.height)

    prompt = TrackingPrompt(
        id=str(uuid4()),
        segment_id=body.segment_id,
        timestamp_seconds=body.timestamp_seconds,
        object_class=TrackedObjectClass(body.object_class),
        kind=kind,
        source=PromptSource.USER,
        point=point,
        box=box,
    )
    tracking.save_user_prompt(prompt)
    return {"segment_id": body.segment_id, "accepted": True}
