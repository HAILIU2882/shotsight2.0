"""Player listing and rename routes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from shotsight2.api.deps import get_review_service, get_video_library_service
from shotsight2.services.review import ReviewService
from shotsight2.services.video_library import VideoLibraryService

router = APIRouter(prefix="/videos/{video_id}", tags=["players"])


class RenamePlayerRequest(BaseModel):
    """Request body for renaming a player's display name."""

    display_name: str

    @field_validator("display_name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Display name must not be blank")
        return v


@router.get("/players")
def list_players(
    video_id: str,
    library: Annotated[VideoLibraryService, Depends(get_video_library_service)],
) -> list[dict[str, Any]]:
    """Return all player tracks for a video with display names and confidence scores."""
    detail = library.get_video_detail(video_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Video {video_id!r} not found")
    return [dataclasses.asdict(p) for p in detail.players]


@router.patch("/players/{player_track_id}", status_code=200)
def rename_player(
    video_id: str,
    player_track_id: str,
    body: RenamePlayerRequest,
    review: Annotated[ReviewService, Depends(get_review_service)],
) -> dict[str, Any]:
    """Rename a player's display name without changing their track ID.

    Raises 422 when the display name is blank.
    """
    review.rename_player(player_track_id, body.display_name)
    return {
        "player_track_id": player_track_id,
        "display_name": body.display_name,
        "updated_at": datetime.now(UTC).isoformat(),
    }
