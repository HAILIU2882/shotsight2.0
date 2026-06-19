"""Human review service: corrections, manual attempts, player renames, and queue ordering."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from shotsight2.domain.persistence import (
    EffectiveShotAttempt,
    JsonValue,
    PlayerTrack,
    ReviewCorrection,
    ReviewStatus,
    ShotAttempt,
    ShotLocation,
    ShotOutcome,
)
from shotsight2.domain.review import CorrectionField, ReviewQueueItem, build_review_queue
from shotsight2.domain.statistics import VideoStatistics


class CorrectionRepository(Protocol):
    """Repository surface required to append and read correction history."""

    def add(self, correction: ReviewCorrection) -> None: ...
    def list_for_attempt(self, attempt_id: str) -> list[ReviewCorrection]: ...


class EffectiveShotReader(Protocol):
    """Repository surface required to read and write effective attempt projections."""

    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]: ...
    def add_manual_attempt(self, attempt: ShotAttempt, location: ShotLocation | None = None) -> None: ...


class PlayerRenameRepository(Protocol):
    """Repository surface required to rename a player's display name."""

    def rename_display_name(self, player_track_id: str, display_name: str) -> None: ...
    def list_for_video(self, video_id: str) -> list[PlayerTrack]: ...


class StatisticsProvider(Protocol):
    """Statistics surface required to recalculate aggregates after a change."""

    def summarize_video(self, video_id: str) -> VideoStatistics: ...


def _default_id() -> str:
    return str(uuid4())


def _serialize_location(location: ShotLocation) -> JsonValue:
    """Serialize a ShotLocation to a JSON-compatible dict for correction storage."""
    return {
        "id": location.id,
        "shot_attempt_id": location.shot_attempt_id,
        "court_x_m": location.court_x_m,
        "court_y_m": location.court_y_m,
        "normalized_x": location.normalized_x,
        "normalized_y": location.normalized_y,
        "region": location.region,
        "indicative": location.indicative,
    }


def _validate_location(location: ShotLocation) -> None:
    """Raise ValueError when the location has invalid coordinates or is missing a region."""
    if not (0.0 <= location.normalized_x <= 1.0 and 0.0 <= location.normalized_y <= 1.0):
        raise ValueError("Normalized location coordinates must be in [0, 1]")
    if not location.region.strip():
        raise ValueError("Location region must not be empty")


class ReviewService:
    """Apply human corrections while preserving automatic evidence and audit history."""

    def __init__(
        self,
        corrections: CorrectionRepository,
        attempts: EffectiveShotReader,
        players: PlayerRenameRepository,
        statistics: StatisticsProvider,
        *,
        id_factory: Callable[[], str] | None = None,
        low_confidence_threshold: float = 0.5,
    ) -> None:
        if not 0 <= low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between zero and one")
        self._corrections = corrections
        self._attempts = attempts
        self._players = players
        self._statistics = statistics
        self._id_factory: Callable[[], str] = id_factory or _default_id
        self._low_confidence_threshold = low_confidence_threshold

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_effective(self, video_id: str, attempt_id: str) -> EffectiveShotAttempt:
        """Return the current effective attempt, raising ValueError when absent."""
        for attempt in self._attempts.list_effective(video_id):
            if attempt.automatic.id == attempt_id:
                return attempt
        raise ValueError(f"Unknown attempt: {attempt_id}")

    def _make_correction(
        self,
        attempt_id: str,
        field: CorrectionField,
        prior: JsonValue,
        new_value: JsonValue,
        now: datetime,
    ) -> ReviewCorrection:
        return ReviewCorrection(
            id=self._id_factory(),
            shot_attempt_id=attempt_id,
            field=field.value,
            previous_value=prior,
            corrected_value=new_value,
            created_at=now,
        )

    def _mark_reviewed(
        self,
        attempt_id: str,
        effective: EffectiveShotAttempt,
        now: datetime,
    ) -> None:
        """Append a REVIEWED status correction unless the attempt is already reviewed."""
        if effective.review_status is ReviewStatus.REVIEWED:
            return
        self._corrections.add(
            self._make_correction(
                attempt_id,
                CorrectionField.REVIEW_STATUS,
                effective.review_status.value,
                ReviewStatus.REVIEWED.value,
                now,
            )
        )

    @staticmethod
    def _check_active(effective: EffectiveShotAttempt) -> None:
        if effective.removed:
            raise ValueError("Cannot correct a removed attempt")

    # ------------------------------------------------------------------
    # REV-002: Player rename
    # ------------------------------------------------------------------

    def rename_player(self, player_track_id: str, new_display_name: str) -> None:
        """Rename a player's display name while preserving their local track ID.

        Raises ValueError when the display name is blank.
        """
        if not new_display_name.strip():
            raise ValueError("Display name must not be empty")
        self._players.rename_display_name(player_track_id, new_display_name)

    # ------------------------------------------------------------------
    # REV-003: Make/miss/uncertain override
    # ------------------------------------------------------------------

    def override_outcome(
        self,
        video_id: str,
        attempt_id: str,
        new_outcome: ShotOutcome,
        now: datetime,
    ) -> VideoStatistics:
        """Override the outcome for one attempt and recalculate statistics.

        Raises ValueError when the attempt is removed or unknown.
        """
        effective = self._find_effective(video_id, attempt_id)
        self._check_active(effective)
        self._corrections.add(
            self._make_correction(
                attempt_id,
                CorrectionField.OUTCOME,
                effective.outcome.value,
                new_outcome.value,
                now,
            )
        )
        self._mark_reviewed(attempt_id, effective, now)
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-004: Shooter attribution override
    # ------------------------------------------------------------------

    def override_shooter(
        self,
        video_id: str,
        attempt_id: str,
        new_shooter_id: str | None,
        valid_player_ids: frozenset[str],
        now: datetime,
    ) -> VideoStatistics:
        """Override shooter attribution for one attempt and recalculate statistics.

        Raises ValueError when new_shooter_id is not None and not in valid_player_ids,
        or when the attempt is removed or unknown.
        """
        if new_shooter_id is not None and new_shooter_id not in valid_player_ids:
            raise ValueError(f"Unknown player track: {new_shooter_id}")
        effective = self._find_effective(video_id, attempt_id)
        self._check_active(effective)
        prior: JsonValue = effective.shooter_track_id
        self._corrections.add(
            self._make_correction(attempt_id, CorrectionField.SHOOTER_TRACK_ID, prior, new_shooter_id, now)
        )
        self._mark_reviewed(attempt_id, effective, now)
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-005: Shot-type override
    # ------------------------------------------------------------------

    def override_shot_type(
        self,
        video_id: str,
        attempt_id: str,
        new_shot_type: str,
        now: datetime,
    ) -> VideoStatistics:
        """Override the shot type for one attempt and recalculate statistics.

        Raises ValueError when new_shot_type is blank, or the attempt is removed or unknown.
        """
        if not new_shot_type.strip():
            raise ValueError("Shot type must not be empty")
        effective = self._find_effective(video_id, attempt_id)
        self._check_active(effective)
        self._corrections.add(
            self._make_correction(
                attempt_id,
                CorrectionField.SHOT_TYPE,
                effective.shot_type,
                new_shot_type,
                now,
            )
        )
        self._mark_reviewed(attempt_id, effective, now)
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-006: Location override
    # ------------------------------------------------------------------

    def override_location(
        self,
        video_id: str,
        attempt_id: str,
        new_location: ShotLocation | None,
        now: datetime,
    ) -> VideoStatistics:
        """Override the shot location (or clear it) and recalculate statistics.

        Raises ValueError when new_location has invalid coordinates or region,
        or when the attempt is removed or unknown.
        """
        if new_location is not None:
            _validate_location(new_location)
        effective = self._find_effective(video_id, attempt_id)
        self._check_active(effective)
        prior: JsonValue = _serialize_location(effective.location) if effective.location is not None else None
        new_value: JsonValue = _serialize_location(new_location) if new_location is not None else None
        self._corrections.add(self._make_correction(attempt_id, CorrectionField.LOCATION, prior, new_value, now))
        self._mark_reviewed(attempt_id, effective, now)
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-007: Manual attempt creation
    # ------------------------------------------------------------------

    def create_manual_attempt(
        self,
        run_id: str,
        video_id: str,
        release_seconds: float,
        shot_type: str,
        outcome: ShotOutcome,
        *,
        shooter_track_id: str | None = None,
        valid_player_ids: frozenset[str] = frozenset(),
        location: ShotLocation | None = None,
    ) -> VideoStatistics:
        """Create a manual attempt with required release timestamp and recalculate statistics.

        Raises ValueError for invalid release time, blank shot type, unknown shooter,
        or invalid location coordinates.
        """
        if release_seconds < 0:
            raise ValueError("Release time must be non-negative")
        if not shot_type.strip():
            raise ValueError("Shot type must not be empty")
        if shooter_track_id is not None and valid_player_ids and shooter_track_id not in valid_player_ids:
            raise ValueError(f"Unknown player track: {shooter_track_id}")
        if location is not None:
            _validate_location(location)

        attempt_id = self._id_factory()
        attempt = ShotAttempt(
            id=attempt_id,
            analysis_run_id=run_id,
            shooter_track_id=shooter_track_id,
            release_seconds=release_seconds,
            automatic_outcome=outcome,
            shot_type=shot_type,
            confidence=1.0,
            review_status=ReviewStatus.REVIEWED,
            evidence={},
            manual=True,
        )
        if location is not None:
            loc = ShotLocation(
                id=self._id_factory(),
                shot_attempt_id=attempt_id,
                court_x_m=location.court_x_m,
                court_y_m=location.court_y_m,
                normalized_x=location.normalized_x,
                normalized_y=location.normalized_y,
                region=location.region,
                indicative=location.indicative,
            )
        else:
            loc = None
        self._attempts.add_manual_attempt(attempt, loc)
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-008: Effective attempt removal
    # ------------------------------------------------------------------

    def remove_attempt(
        self,
        video_id: str,
        attempt_id: str,
        now: datetime,
    ) -> VideoStatistics:
        """Flag an attempt as removed without deleting automatic evidence.

        Raises ValueError when the attempt is already removed or unknown.
        """
        effective = self._find_effective(video_id, attempt_id)
        if effective.removed:
            raise ValueError("Attempt is already removed")
        self._corrections.add(self._make_correction(attempt_id, CorrectionField.REMOVED, False, True, now))
        return self._statistics.summarize_video(video_id)

    def restore_attempt(
        self,
        video_id: str,
        attempt_id: str,
        now: datetime,
    ) -> VideoStatistics:
        """Undo a removal by appending a removed=False correction.

        Raises ValueError when the attempt is not removed or unknown.
        """
        effective = self._find_effective(video_id, attempt_id)
        if not effective.removed:
            raise ValueError("Attempt is not removed")
        self._corrections.add(self._make_correction(attempt_id, CorrectionField.REMOVED, True, False, now))
        return self._statistics.summarize_video(video_id)

    # ------------------------------------------------------------------
    # REV-009 / REV-011: Review queue
    # ------------------------------------------------------------------

    def build_review_queue(self, video_id: str) -> tuple[ReviewQueueItem, ...]:
        """Return the review queue ordered by uncertainty and confidence for a video."""
        effective = self._attempts.list_effective(video_id)
        return build_review_queue(effective, low_confidence_threshold=self._low_confidence_threshold)
