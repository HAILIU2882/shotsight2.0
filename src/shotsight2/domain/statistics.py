"""Deterministic statistics derived from effective shot attempts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from shotsight2.domain.persistence import EffectiveShotAttempt, PlayerTrack, ReviewStatus, ShotOutcome

TWO_POINT = "TWO_POINT"
THREE_POINT = "THREE_POINT"
KNOWN_SHOT_TYPES = (TWO_POINT, THREE_POINT)


@dataclass(frozen=True, slots=True)
class ShotSummary:
    """Outcome counts and a raw ratio for a group of effective attempts."""

    attempts: int
    makes: int
    misses: int
    uncertain: int
    shooting_percentage: float


@dataclass(frozen=True, slots=True)
class ShotTypeSummary:
    """Breakdown for one effective shot type."""

    shot_type: str
    totals: ShotSummary


@dataclass(frozen=True, slots=True)
class PlayerShotSummary:
    """Breakdown for one video-local player identity."""

    player_id: str | None
    local_label: str | None
    display_name: str | None
    totals: ShotSummary
    two_point: ShotSummary
    three_point: ShotSummary


@dataclass(frozen=True, slots=True)
class ReviewStatusSummary:
    """Breakdown for one review state."""

    review_status: ReviewStatus
    totals: ShotSummary


@dataclass(frozen=True, slots=True)
class ShotChartPoint:
    """Raw attempt point data suitable for shot charts and heatmaps."""

    attempt_id: str
    player_id: str | None
    release_seconds: float
    outcome: ShotOutcome
    shot_type: str
    review_status: ReviewStatus
    confidence: float
    low_confidence: bool
    court_x_m: float | None
    court_y_m: float | None
    normalized_x: float | None
    normalized_y: float | None
    region: str | None
    indicative: bool


@dataclass(frozen=True, slots=True)
class LocationGroupSummary:
    """Chart-ready aggregate for one region and shot-type bucket."""

    region: str | None
    shot_type: str
    totals: ShotSummary


@dataclass(frozen=True, slots=True)
class VideoStatistics:
    """Complete statistics query model for one video."""

    video_id: str
    totals: ShotSummary
    two_point: ShotSummary
    three_point: ShotSummary
    shot_types: tuple[ShotTypeSummary, ...]
    players: tuple[PlayerShotSummary, ...]
    review_statuses: tuple[ReviewStatusSummary, ...]
    reviewed_attempts: int
    automatic_attempts: int
    low_confidence_attempts: int
    shot_chart_points: tuple[ShotChartPoint, ...]
    location_groups: tuple[LocationGroupSummary, ...]


def calculate_video_statistics(
    video_id: str,
    attempts: Sequence[EffectiveShotAttempt],
    players: Sequence[PlayerTrack],
    *,
    low_confidence_threshold: float = 0.5,
) -> VideoStatistics:
    """Calculate all aggregate statistics from the current effective attempts.

    Removed attempts are excluded. Zero-attempt percentages are defined as
    ``0.0`` so callers can render totals without inventing fallback values.
    """

    if not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be between zero and one")

    active_attempts = tuple(attempt for attempt in attempts if not attempt.removed)
    player_by_id = {player.id: player for player in players}

    shot_type_summaries = _shot_type_summaries(active_attempts)
    shot_type_by_key = {summary.shot_type: summary.totals for summary in shot_type_summaries}
    review_status_summaries = _review_status_summaries(active_attempts)
    chart_points = tuple(_chart_point(attempt, low_confidence_threshold) for attempt in active_attempts)

    return VideoStatistics(
        video_id=video_id,
        totals=_summary(active_attempts),
        two_point=shot_type_by_key[TWO_POINT],
        three_point=shot_type_by_key[THREE_POINT],
        shot_types=shot_type_summaries,
        players=_player_summaries(active_attempts, player_by_id, players),
        review_statuses=review_status_summaries,
        reviewed_attempts=sum(1 for attempt in active_attempts if attempt.review_status is ReviewStatus.REVIEWED),
        automatic_attempts=sum(
            1
            for attempt in active_attempts
            if not attempt.automatic.manual and attempt.review_status is ReviewStatus.UNREVIEWED
        ),
        low_confidence_attempts=sum(
            1 for attempt in active_attempts if attempt.automatic.confidence < low_confidence_threshold
        ),
        shot_chart_points=chart_points,
        location_groups=_location_groups(active_attempts),
    )


def _summary(attempts: Iterable[EffectiveShotAttempt]) -> ShotSummary:
    items = tuple(attempts)
    makes = sum(1 for attempt in items if attempt.outcome is ShotOutcome.MADE)
    misses = sum(1 for attempt in items if attempt.outcome is ShotOutcome.MISSED)
    uncertain = sum(1 for attempt in items if attempt.outcome is ShotOutcome.UNCERTAIN)
    total = len(items)
    return ShotSummary(
        attempts=total,
        makes=makes,
        misses=misses,
        uncertain=uncertain,
        shooting_percentage=makes / total if total else 0.0,
    )


def _shot_type_summaries(attempts: Sequence[EffectiveShotAttempt]) -> tuple[ShotTypeSummary, ...]:
    observed = {attempt.shot_type for attempt in attempts}
    ordered = (*KNOWN_SHOT_TYPES, *tuple(sorted(observed.difference(KNOWN_SHOT_TYPES))))
    return tuple(
        ShotTypeSummary(
            shot_type=shot_type,
            totals=_summary(attempt for attempt in attempts if attempt.shot_type == shot_type),
        )
        for shot_type in ordered
    )


def _player_summaries(
    attempts: Sequence[EffectiveShotAttempt],
    player_by_id: dict[str, PlayerTrack],
    players: Sequence[PlayerTrack],
) -> tuple[PlayerShotSummary, ...]:
    by_player: dict[str | None, list[EffectiveShotAttempt]] = defaultdict(list)
    for attempt in attempts:
        by_player[attempt.shooter_track_id].append(attempt)

    known_order = tuple(player.id for player in players if player.id in by_player)
    unknown_order = tuple(
        sorted(player_id for player_id in by_player if player_id is not None and player_id not in player_by_id)
    )
    unassigned_order: tuple[None, ...] = (None,) if None in by_player else ()
    ordered_player_ids: tuple[str | None, ...] = (*known_order, *unknown_order, *unassigned_order)

    return tuple(
        _player_summary(player_id, by_player[player_id], player_by_id.get(player_id) if player_id is not None else None)
        for player_id in ordered_player_ids
    )


def _player_summary(
    player_id: str | None,
    attempts: Sequence[EffectiveShotAttempt],
    player: PlayerTrack | None,
) -> PlayerShotSummary:
    return PlayerShotSummary(
        player_id=player_id,
        local_label=None if player is None else player.local_label,
        display_name=None if player is None else player.display_name,
        totals=_summary(attempts),
        two_point=_summary(attempt for attempt in attempts if attempt.shot_type == TWO_POINT),
        three_point=_summary(attempt for attempt in attempts if attempt.shot_type == THREE_POINT),
    )


def _review_status_summaries(attempts: Sequence[EffectiveShotAttempt]) -> tuple[ReviewStatusSummary, ...]:
    return tuple(
        ReviewStatusSummary(
            review_status=status,
            totals=_summary(attempt for attempt in attempts if attempt.review_status is status),
        )
        for status in ReviewStatus
    )


def _chart_point(attempt: EffectiveShotAttempt, low_confidence_threshold: float) -> ShotChartPoint:
    location = attempt.location
    return ShotChartPoint(
        attempt_id=attempt.automatic.id,
        player_id=attempt.shooter_track_id,
        release_seconds=attempt.automatic.release_seconds,
        outcome=attempt.outcome,
        shot_type=attempt.shot_type,
        review_status=attempt.review_status,
        confidence=attempt.automatic.confidence,
        low_confidence=attempt.automatic.confidence < low_confidence_threshold,
        court_x_m=None if location is None else location.court_x_m,
        court_y_m=None if location is None else location.court_y_m,
        normalized_x=None if location is None else location.normalized_x,
        normalized_y=None if location is None else location.normalized_y,
        region=None if location is None else location.region,
        indicative=False if location is None else location.indicative,
    )


def _location_groups(attempts: Sequence[EffectiveShotAttempt]) -> tuple[LocationGroupSummary, ...]:
    raw_group_keys = {
        (attempt.location.region if attempt.location is not None else None, attempt.shot_type) for attempt in attempts
    }
    group_keys = sorted(
        raw_group_keys,
        key=lambda item: ("" if item[0] is None else item[0], item[1]),
    )
    return tuple(
        LocationGroupSummary(
            region=region,
            shot_type=shot_type,
            totals=_summary(
                attempt
                for attempt in attempts
                if (attempt.location.region if attempt.location is not None else None) == region
                and attempt.shot_type == shot_type
            ),
        )
        for region, shot_type in group_keys
    )
