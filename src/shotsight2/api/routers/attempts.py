"""Attempt list, create, update, and delete routes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from shotsight2.api.deps import get_review_service
from shotsight2.domain.persistence import ShotLocation, ShotOutcome
from shotsight2.services.review import ReviewService

router = APIRouter(prefix="/videos/{video_id}", tags=["attempts"])


class LocationSchema(BaseModel):
    """Shot location in both court coordinates and normalized image coordinates."""

    court_x_m: float | None = None
    court_y_m: float | None = None
    normalized_x: float
    normalized_y: float
    region: str
    indicative: bool = False


class CreateAttemptRequest(BaseModel):
    """Request body for manually creating a shot attempt."""

    run_id: str
    release_seconds: float
    shot_type: str
    outcome: str
    shooter_track_id: str | None = None
    location: LocationSchema | None = None

    @field_validator("shot_type")
    @classmethod
    def _non_empty_shot_type(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("shot_type must not be blank")
        return v

    @field_validator("outcome")
    @classmethod
    def _valid_outcome(cls, v: str) -> str:
        try:
            ShotOutcome(v)
        except ValueError:
            raise ValueError(f"Invalid outcome: {v!r}") from None
        return v


class UpdateAttemptRequest(BaseModel):
    """Request body for updating one field of an existing attempt."""

    field: str
    value: Any

    @field_validator("field")
    @classmethod
    def _valid_field(cls, v: str) -> str:
        allowed = {"outcome", "shooter_track_id", "shot_type", "location", "removed"}
        if v not in allowed:
            raise ValueError(f"Unknown update field: {v!r}")
        return v


@router.get("/attempts")
def list_attempts(
    video_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
) -> list[dict[str, Any]]:
    """Return the prioritised review queue for a video."""
    queue = review.build_review_queue(video_id)
    return [dataclasses.asdict(item) for item in queue]


@router.post("/attempts", status_code=201)
def create_attempt(
    video_id: str,
    body: CreateAttemptRequest,
    review: Annotated[ReviewService, Depends(get_review_service)],
) -> dict[str, Any]:
    """Create a manual shot attempt with required release timestamp.

    Returns 201 with updated video statistics.
    Raises 422 for invalid timestamps, blank types, or unknown shooters.
    """
    loc: ShotLocation | None = None
    if body.location is not None:
        loc = ShotLocation(
            id=_new_id(),
            shot_attempt_id="",
            court_x_m=body.location.court_x_m,
            court_y_m=body.location.court_y_m,
            normalized_x=body.location.normalized_x,
            normalized_y=body.location.normalized_y,
            region=body.location.region,
            indicative=body.location.indicative,
        )
    stats = review.create_manual_attempt(
        run_id=body.run_id,
        video_id=video_id,
        release_seconds=body.release_seconds,
        shot_type=body.shot_type,
        outcome=ShotOutcome(body.outcome),
        shooter_track_id=body.shooter_track_id,
        location=loc,
    )
    return dataclasses.asdict(stats)


@router.patch("/attempts/{attempt_id}")
def update_attempt(
    video_id: str,
    attempt_id: str,
    body: UpdateAttemptRequest,
    review: Annotated[ReviewService, Depends(get_review_service)],
) -> dict[str, Any]:
    """Apply a field correction to one attempt and return updated statistics.

    Supported fields: outcome, shooter_track_id, shot_type, location, removed.
    Raises 422 on validation errors.
    Raises 409 when attempting to correct a removed attempt.
    """
    now = datetime.now(UTC)
    if body.field == "outcome":
        try:
            outcome = ShotOutcome(body.value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid outcome: {body.value!r}") from exc
        stats = review.override_outcome(video_id, attempt_id, outcome, now)
    elif body.field == "shooter_track_id":
        shooter: str | None = body.value
        stats = review.override_shooter(video_id, attempt_id, shooter, frozenset(), now)
    elif body.field == "shot_type":
        if not isinstance(body.value, str) or not body.value.strip():
            raise HTTPException(status_code=422, detail="shot_type must be a non-blank string")
        stats = review.override_shot_type(video_id, attempt_id, body.value, now)
    elif body.field == "location":
        loc = None
        if body.value is not None:
            d = body.value
            loc = ShotLocation(
                id=_new_id(),
                shot_attempt_id=attempt_id,
                court_x_m=d.get("court_x_m"),
                court_y_m=d.get("court_y_m"),
                normalized_x=float(d["normalized_x"]),
                normalized_y=float(d["normalized_y"]),
                region=str(d.get("region", "")),
                indicative=bool(d.get("indicative", False)),
            )
        stats = review.override_location(video_id, attempt_id, loc, now)
    elif body.field == "removed":
        if body.value:
            stats = review.remove_attempt(video_id, attempt_id, now)
        else:
            stats = review.restore_attempt(video_id, attempt_id, now)
    else:
        raise HTTPException(status_code=422, detail=f"Unsupported field: {body.field!r}")
    return dataclasses.asdict(stats)


@router.delete("/attempts/{attempt_id}", status_code=204)
def delete_attempt(
    video_id: str,
    attempt_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
) -> None:
    """Remove an attempt from effective results without deleting automatic evidence.

    Raises 409 when the attempt is already removed.
    """
    review.remove_attempt(video_id, attempt_id, datetime.now(UTC))


def _new_id() -> str:
    from uuid import uuid4

    return str(uuid4())
