"""Statistics tests for correction-aware effective attempts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shotsight2.domain import (
    EffectiveShotAttempt,
    PlayerTrack,
    ReviewStatus,
    ShotAttempt,
    ShotLocation,
    ShotOutcome,
    ShotSummary,
    calculate_video_statistics,
)
from shotsight2.services import StatisticsService


class MutableAttemptReader:
    """Tiny fake that proves statistics are recalculated from fresh effective values."""

    def __init__(self, attempts: list[EffectiveShotAttempt]) -> None:
        self.attempts = attempts

    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]:
        return list(self.attempts)


class StaticPlayerReader:
    """Tiny fake for video-local player names."""

    def __init__(self, players: list[PlayerTrack]) -> None:
        self.players = players

    def list_for_video(self, video_id: str) -> list[PlayerTrack]:
        return list(self.players)


def player(player_id: str, label: str, display_name: str | None = None) -> PlayerTrack:
    return PlayerTrack(
        player_id,
        "run-1",
        "video-1",
        label,
        display_name or label,
        0.9,
    )


def location(
    attempt_id: str,
    *,
    region: str = "RIGHT_WING",
    x: float | None = 7.1,
    y: float | None = 2.0,
    normalized_x: float = 0.76,
    normalized_y: float = 0.42,
    indicative: bool = False,
) -> ShotLocation:
    return ShotLocation(
        f"location-{attempt_id}",
        attempt_id,
        x,
        y,
        normalized_x,
        normalized_y,
        region,
        indicative,
    )


def effective(
    attempt_id: str,
    *,
    player_id: str | None = "player-1",
    outcome: ShotOutcome = ShotOutcome.MADE,
    automatic_outcome: ShotOutcome | None = None,
    shot_type: str = "TWO_POINT",
    automatic_shot_type: str | None = None,
    confidence: float = 0.9,
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
    release_seconds: float = 1.0,
    shot_location: ShotLocation | None = None,
    removed: bool = False,
    manual: bool = False,
) -> EffectiveShotAttempt:
    automatic = ShotAttempt(
        attempt_id,
        "run-1",
        player_id,
        release_seconds,
        automatic_outcome or outcome,
        automatic_shot_type or shot_type,
        confidence,
        ReviewStatus.UNREVIEWED,
        {"release_frame": int(release_seconds * 30)},
        manual,
    )
    return EffectiveShotAttempt(
        automatic=automatic,
        shooter_track_id=player_id,
        outcome=outcome,
        shot_type=shot_type,
        review_status=review_status,
        location=shot_location if shot_location is not None else location(attempt_id),
        removed=removed,
    )


def test_empty_dataset_has_zero_counts_and_defined_percentages() -> None:
    stats = calculate_video_statistics("video-1", [], [])

    assert stats.totals == ShotSummary(0, 0, 0, 0, 0.0)
    assert stats.two_point == ShotSummary(0, 0, 0, 0, 0.0)
    assert stats.three_point == ShotSummary(0, 0, 0, 0, 0.0)
    assert [summary.shot_type for summary in stats.shot_types] == ["TWO_POINT", "THREE_POINT"]
    assert stats.players == ()
    assert stats.shot_chart_points == ()
    assert stats.location_groups == ()


def test_all_made_dataset_counts_every_make() -> None:
    attempts = [
        effective("a1", outcome=ShotOutcome.MADE, shot_type="TWO_POINT"),
        effective("a2", outcome=ShotOutcome.MADE, shot_type="THREE_POINT"),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.totals == ShotSummary(2, 2, 0, 0, 1.0)
    assert stats.two_point == ShotSummary(1, 1, 0, 0, 1.0)
    assert stats.three_point == ShotSummary(1, 1, 0, 0, 1.0)


def test_all_missed_dataset_counts_every_miss() -> None:
    attempts = [
        effective("a1", outcome=ShotOutcome.MISSED, shot_type="TWO_POINT"),
        effective("a2", outcome=ShotOutcome.MISSED, shot_type="THREE_POINT"),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.totals == ShotSummary(2, 0, 2, 0, 0.0)
    assert stats.two_point == ShotSummary(1, 0, 1, 0, 0.0)
    assert stats.three_point == ShotSummary(1, 0, 1, 0, 0.0)


def test_mixed_and_uncertain_dataset_keeps_uncertain_separate() -> None:
    attempts = [
        effective("a1", outcome=ShotOutcome.MADE, shot_type="TWO_POINT"),
        effective("a2", outcome=ShotOutcome.MISSED, shot_type="TWO_POINT"),
        effective("a3", outcome=ShotOutcome.UNCERTAIN, shot_type="THREE_POINT"),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.totals.attempts == 3
    assert stats.totals.makes == 1
    assert stats.totals.misses == 1
    assert stats.totals.uncertain == 1
    assert stats.totals.shooting_percentage == pytest.approx(1 / 3)
    assert stats.two_point == ShotSummary(2, 1, 1, 0, 0.5)
    assert stats.three_point == ShotSummary(1, 0, 0, 1, 0.0)


def test_effective_corrections_drive_totals_without_using_automatic_values() -> None:
    corrected = effective(
        "a1",
        outcome=ShotOutcome.MADE,
        automatic_outcome=ShotOutcome.MISSED,
        shot_type="TWO_POINT",
        automatic_shot_type="THREE_POINT",
        review_status=ReviewStatus.REVIEWED,
    )

    stats = calculate_video_statistics("video-1", [corrected], [player("player-1", "Player 1")])

    assert stats.totals == ShotSummary(1, 1, 0, 0, 1.0)
    assert stats.two_point == ShotSummary(1, 1, 0, 0, 1.0)
    assert stats.three_point == ShotSummary(0, 0, 0, 0, 0.0)
    assert stats.reviewed_attempts == 1
    assert stats.automatic_attempts == 0


def test_removed_attempts_are_excluded_from_totals_and_chart_data() -> None:
    attempts = [
        effective("a1", outcome=ShotOutcome.MADE),
        effective("a2", outcome=ShotOutcome.MISSED, removed=True),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.totals == ShotSummary(1, 1, 0, 0, 1.0)
    assert [point.attempt_id for point in stats.shot_chart_points] == ["a1"]
    assert stats.location_groups[0].totals == ShotSummary(1, 1, 0, 0, 1.0)


def test_multiplayer_breakdowns_use_renamed_player_display_names() -> None:
    attempts = [
        effective("a1", player_id="player-1", outcome=ShotOutcome.MADE, shot_type="TWO_POINT"),
        effective("a2", player_id="player-2", outcome=ShotOutcome.MISSED, shot_type="THREE_POINT"),
        effective("a3", player_id=None, outcome=ShotOutcome.MADE, shot_type="THREE_POINT"),
    ]
    players = [
        player("player-1", "Player 1", "Maya"),
        player("player-2", "Player 2", "Jordan"),
    ]

    stats = calculate_video_statistics("video-1", attempts, players)

    assert [(item.player_id, item.local_label, item.display_name) for item in stats.players] == [
        ("player-1", "Player 1", "Maya"),
        ("player-2", "Player 2", "Jordan"),
        (None, None, None),
    ]
    assert stats.players[0].totals == ShotSummary(1, 1, 0, 0, 1.0)
    assert stats.players[1].three_point == ShotSummary(1, 0, 1, 0, 0.0)
    assert stats.players[2].totals == ShotSummary(1, 1, 0, 0, 1.0)


def test_review_status_and_low_confidence_counts_are_grouped() -> None:
    attempts = [
        effective("a1", review_status=ReviewStatus.UNREVIEWED, confidence=0.4),
        effective("a2", review_status=ReviewStatus.REVIEWED, confidence=0.8),
        effective("a3", review_status=ReviewStatus.REVIEWED, confidence=0.49, manual=True),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.reviewed_attempts == 2
    assert stats.automatic_attempts == 1
    assert stats.low_confidence_attempts == 2
    assert [(item.review_status, item.totals.attempts) for item in stats.review_statuses] == [
        (ReviewStatus.UNREVIEWED, 1),
        (ReviewStatus.REVIEWED, 2),
    ]
    assert [point.low_confidence for point in stats.shot_chart_points] == [True, False, True]


def test_chart_ready_points_and_location_groups_are_unformatted() -> None:
    attempts = [
        effective(
            "a1",
            outcome=ShotOutcome.MADE,
            shot_type="THREE_POINT",
            shot_location=location("a1", region="LEFT_CORNER", normalized_x=0.1, normalized_y=0.8),
        ),
        effective(
            "a2",
            outcome=ShotOutcome.MISSED,
            shot_type="THREE_POINT",
            shot_location=location("a2", region="LEFT_CORNER", normalized_x=0.12, normalized_y=0.79),
        ),
        effective(
            "a3",
            outcome=ShotOutcome.MADE,
            shot_type="TWO_POINT",
            shot_location=location("a3", region="PAINT", x=None, y=None, indicative=True),
        ),
    ]

    stats = calculate_video_statistics("video-1", attempts, [player("player-1", "Player 1")])

    assert stats.shot_chart_points[0].normalized_x == 0.1
    assert stats.shot_chart_points[0].region == "LEFT_CORNER"
    assert stats.shot_chart_points[2].court_x_m is None
    assert stats.shot_chart_points[2].indicative is True
    assert [(group.region, group.shot_type, group.totals) for group in stats.location_groups] == [
        ("LEFT_CORNER", "THREE_POINT", ShotSummary(2, 1, 1, 0, 0.5)),
        ("PAINT", "TWO_POINT", ShotSummary(1, 1, 0, 0, 1.0)),
    ]


def test_statistics_service_recalculates_after_effective_values_change() -> None:
    reader = MutableAttemptReader([effective("a1", outcome=ShotOutcome.MISSED)])
    service = StatisticsService(reader, StaticPlayerReader([player("player-1", "Player 1")]))

    before = service.summarize_video("video-1")
    reader.attempts = [replace(reader.attempts[0], outcome=ShotOutcome.MADE, review_status=ReviewStatus.REVIEWED)]
    after = service.summarize_video("video-1")

    assert before.totals == ShotSummary(1, 0, 1, 0, 0.0)
    assert after.totals == ShotSummary(1, 1, 0, 0, 1.0)
    assert after.reviewed_attempts == 1


def test_low_confidence_threshold_is_validated() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        calculate_video_statistics("video-1", [], [], low_confidence_threshold=1.1)
    with pytest.raises(ValueError, match="between zero and one"):
        StatisticsService(MutableAttemptReader([]), StaticPlayerReader([]), low_confidence_threshold=-0.1)
