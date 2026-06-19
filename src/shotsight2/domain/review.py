"""Domain models for correction commands and the review queue."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from shotsight2.domain.persistence import EffectiveShotAttempt, ReviewStatus, ShotOutcome

LOW_CONFIDENCE_THRESHOLD = 0.5

__all__ = [
    "LOW_CONFIDENCE_THRESHOLD",
    "CorrectionField",
    "ReviewQueueItem",
    "ReviewStatus",
    "build_review_queue",
]


class CorrectionField(StrEnum):
    """Named fields that a user may correct on an effective shot attempt."""

    OUTCOME = "outcome"
    SHOOTER_TRACK_ID = "shooter_track_id"
    SHOT_TYPE = "shot_type"
    LOCATION = "location"
    REMOVED = "removed"
    REVIEW_STATUS = "review_status"


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    """One entry in the prioritised human-review queue."""

    attempt_id: str
    release_seconds: float
    outcome: ShotOutcome
    shot_type: str
    confidence: float
    review_status: ReviewStatus
    removed: bool
    is_uncertain: bool
    is_low_confidence: bool
    shooter_track_id: str | None
    location_available: bool


def build_review_queue(
    attempts: Sequence[EffectiveShotAttempt],
    *,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> tuple[ReviewQueueItem, ...]:
    """Return active attempts ordered: uncertain-unreviewed first, then low-confidence-unreviewed, then by release time.

    Removed attempts are excluded.
    """
    if not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be between zero and one")

    items = [
        ReviewQueueItem(
            attempt_id=a.automatic.id,
            release_seconds=a.automatic.release_seconds,
            outcome=a.outcome,
            shot_type=a.shot_type,
            confidence=a.automatic.confidence,
            review_status=a.review_status,
            removed=a.removed,
            is_uncertain=a.outcome is ShotOutcome.UNCERTAIN,
            is_low_confidence=a.automatic.confidence < low_confidence_threshold,
            shooter_track_id=a.shooter_track_id,
            location_available=a.location is not None,
        )
        for a in attempts
        if not a.removed
    ]

    def _sort_key(item: ReviewQueueItem) -> tuple[int, int, int, float]:
        uncertain_first = 0 if (item.is_uncertain and item.review_status is ReviewStatus.UNREVIEWED) else 1
        low_conf_first = 0 if (item.is_low_confidence and item.review_status is ReviewStatus.UNREVIEWED) else 1
        reviewed_last = 0 if item.review_status is ReviewStatus.UNREVIEWED else 1
        return (uncertain_first, low_conf_first, reviewed_last, item.release_seconds)

    return tuple(sorted(items, key=_sort_key))
