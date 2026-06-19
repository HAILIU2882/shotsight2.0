"""Attempt list, edit, create, remove, and restore routes."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from shotsight2.api.deps import get_review_service
from shotsight2.domain.persistence import ShotOutcome
from shotsight2.presentation import jinja_templates
from shotsight2.presentation.routes._locale import locale_param
from shotsight2.services.review import ReviewService

router = APIRouter(tags=["presentation"])


@router.get("/videos/{video_id}/attempts", response_class=HTMLResponse)
def attempts_page(
    request: Request,
    video_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Render the prioritised attempt review queue."""
    queue = review.build_review_queue(video_id)
    return jinja_templates.TemplateResponse(
        request,
        "attempts.html",
        {"locale": locale, "video_id": video_id, "attempts": list(queue), "error": None, "success": None},
    )


@router.get("/videos/{video_id}/attempts/new", response_class=HTMLResponse)
def new_attempt_page(
    request: Request,
    video_id: str,
    locale: Annotated[str, Depends(locale_param)],
    run_id: str = "",
) -> HTMLResponse:
    """Show the form for manually creating a shot attempt."""
    return jinja_templates.TemplateResponse(
        request,
        "attempt_new.html",
        {"locale": locale, "video_id": video_id, "run_id": run_id, "error": None, "success": None},
    )


@router.post("/videos/{video_id}/attempts/create", response_class=HTMLResponse, response_model=None)
def create_attempt(
    request: Request,
    video_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
    run_id: Annotated[str, Form()],
    release_seconds: Annotated[float, Form()],
    shot_type: Annotated[str, Form()],
    outcome: Annotated[str, Form()],
) -> Response:
    """Process the manual attempt creation form."""
    try:
        shot_outcome = ShotOutcome(outcome)
    except ValueError:
        return jinja_templates.TemplateResponse(
            request,
            "attempt_new.html",
            {
                "locale": locale,
                "video_id": video_id,
                "run_id": run_id,
                "error": f"Invalid outcome: {outcome!r}",
                "success": None,
            },
            status_code=422,
        )
    review.create_manual_attempt(
        run_id=run_id,
        video_id=video_id,
        release_seconds=release_seconds,
        shot_type=shot_type,
        outcome=shot_outcome,
        shooter_track_id=None,
        location=None,
    )
    return RedirectResponse(url=f"/videos/{video_id}/attempts?locale={locale}", status_code=303)


@router.get("/videos/{video_id}/attempts/{attempt_id}", response_class=HTMLResponse)
def edit_attempt_page(
    request: Request,
    video_id: str,
    attempt_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> HTMLResponse:
    """Show the attempt edit form with prev/next navigation."""
    queue = review.build_review_queue(video_id)
    ids = [a.attempt_id for a in queue]
    attempt = next((a for a in queue if a.attempt_id == attempt_id), None)
    if attempt is None:
        raise HTTPException(status_code=404, detail=f"Attempt {attempt_id!r} not found")
    idx = ids.index(attempt_id)
    prev_id = ids[idx - 1] if idx > 0 else None
    next_id = ids[idx + 1] if idx < len(ids) - 1 else None
    return jinja_templates.TemplateResponse(
        request,
        "attempt_edit.html",
        {
            "locale": locale,
            "video_id": video_id,
            "attempt": attempt,
            "idx": idx,
            "prev_id": prev_id,
            "next_id": next_id,
            "error": None,
            "success": None,
        },
    )


@router.post("/videos/{video_id}/attempts/{attempt_id}/update", response_class=HTMLResponse, response_model=None)
def update_attempt(
    request: Request,
    video_id: str,
    attempt_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
    outcome: Annotated[str, Form()],
    shot_type: Annotated[str, Form()],
    shooter_track_id: Annotated[str, Form()] = "",
) -> Response:
    """Apply outcome/type/shooter corrections via the edit form."""
    now = datetime.now(UTC)
    try:
        shot_outcome = ShotOutcome(outcome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    review.override_outcome(video_id, attempt_id, shot_outcome, now)
    if shot_type.strip():
        review.override_shot_type(video_id, attempt_id, shot_type.strip(), now)
    shooter: str | None = shooter_track_id.strip() or None
    review.override_shooter(video_id, attempt_id, shooter, frozenset(), now)
    return RedirectResponse(url=f"/videos/{video_id}/attempts?locale={locale}", status_code=303)


@router.post("/videos/{video_id}/attempts/{attempt_id}/remove", response_class=HTMLResponse)
def remove_attempt(
    video_id: str,
    attempt_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> RedirectResponse:
    """Mark an attempt as removed."""
    review.remove_attempt(video_id, attempt_id, datetime.now(UTC))
    return RedirectResponse(url=f"/videos/{video_id}/attempts?locale={locale}", status_code=303)


@router.post("/videos/{video_id}/attempts/{attempt_id}/restore", response_class=HTMLResponse)
def restore_attempt(
    video_id: str,
    attempt_id: str,
    review: Annotated[ReviewService, Depends(get_review_service)],
    locale: Annotated[str, Depends(locale_param)],
) -> RedirectResponse:
    """Restore a removed attempt."""
    review.restore_attempt(video_id, attempt_id, datetime.now(UTC))
    return RedirectResponse(url=f"/videos/{video_id}/attempts?locale={locale}", status_code=303)
