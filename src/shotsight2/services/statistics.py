"""Application service for correction-aware video statistics."""

from __future__ import annotations

from typing import Protocol

from shotsight2.domain import EffectiveShotAttempt, PlayerTrack
from shotsight2.domain.statistics import VideoStatistics, calculate_video_statistics


class EffectiveShotAttemptReader(Protocol):
    """Repository surface needed to read correction-aware attempt projections."""

    def list_effective(self, video_id: str) -> list[EffectiveShotAttempt]: ...


class PlayerTrackReader(Protocol):
    """Repository surface needed to resolve video-local player display names."""

    def list_for_video(self, video_id: str) -> list[PlayerTrack]: ...


class StatisticsService:
    """Build statistics from the latest effective attempt and player projections."""

    def __init__(
        self,
        attempts: EffectiveShotAttemptReader,
        players: PlayerTrackReader,
        *,
        low_confidence_threshold: float = 0.5,
    ) -> None:
        if not 0 <= low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between zero and one")
        self._attempts = attempts
        self._players = players
        self._low_confidence_threshold = low_confidence_threshold

    def summarize_video(self, video_id: str) -> VideoStatistics:
        """Read fresh effective values and calculate aggregate statistics."""

        return calculate_video_statistics(
            video_id,
            self._attempts.list_effective(video_id),
            self._players.list_for_video(video_id),
            low_confidence_threshold=self._low_confidence_threshold,
        )
