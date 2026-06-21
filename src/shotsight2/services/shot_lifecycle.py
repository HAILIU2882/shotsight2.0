"""Deterministic shot lifecycle engine over associated tracking evidence."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from shotsight2.domain.calibration import ImagePoint as CalibrationImagePoint
from shotsight2.domain.calibration import RimGeometry, calibration_geometry_from_json
from shotsight2.domain.persistence import Calibration, CameraSegment, ShotAttempt
from shotsight2.domain.shot_lifecycle import (
    IgnoredReleaseCandidate,
    IgnoredReleaseReason,
    ShotAttemptCandidate,
    ShotLifecycleConfidence,
    ShotLifecycleEvent,
    ShotLifecycleEventKind,
    ShotLifecycleEvidence,
    ShotLifecycleEvidenceKind,
    ShotLifecycleState,
    ShotLifecycleTerminal,
)
from shotsight2.domain.track_association import PossessionFrame
from shotsight2.domain.tracking import TrackedObjectClass, TrackObservation, VisibilityState


@dataclass(frozen=True, slots=True)
class ShotLifecycleConfig:
    """Thresholds for deterministic release and terminal lifecycle decisions."""

    minimum_possession_frames: int = 2
    release_window_seconds: float = 0.5
    shot_intent_window_seconds: float = 0.75
    minimum_upward_pixels: float = 8.0
    minimum_rim_approach_pixels: float = 8.0
    rim_approach_radius_multiplier: float = 5.0
    rim_interaction_radius_multiplier: float = 1.8
    immediate_block_seconds: float = 0.35
    block_candidate_normalized_distance: float = 0.2
    airball_minimum_flight_seconds: float = 0.55
    descent_pixels_for_airball: float = 8.0
    uncertainty_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.minimum_possession_frames <= 0:
            raise ValueError("Minimum possession frames must be positive")
        values = (
            self.release_window_seconds,
            self.shot_intent_window_seconds,
            self.minimum_upward_pixels,
            self.minimum_rim_approach_pixels,
            self.rim_approach_radius_multiplier,
            self.rim_interaction_radius_multiplier,
            self.immediate_block_seconds,
            self.airball_minimum_flight_seconds,
            self.descent_pixels_for_airball,
            self.uncertainty_timeout_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Shot lifecycle thresholds must be positive")
        if self.block_candidate_normalized_distance < 0:
            raise ValueError("Block distance threshold cannot be negative")


@dataclass(frozen=True, slots=True)
class ShotLifecycleResult:
    """Lifecycle output for one analysis run."""

    candidates: tuple[ShotAttemptCandidate, ...]
    ignored_releases: tuple[IgnoredReleaseCandidate, ...]

    @property
    def attempts(self) -> tuple[ShotAttempt, ...]:
        """Return persistence-ready automatic shot attempts."""

        return tuple(candidate.to_shot_attempt() for candidate in self.candidates)


@dataclass(frozen=True, slots=True)
class _RimTarget:
    segment_id: str
    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    confidence: float
    evidence_id: str
    source: ShotLifecycleEvidenceKind

    def normalized_distance(self, observation: TrackObservation) -> float:
        dx = (observation.centroid.x - self.center_x) / self.radius_x
        dy = (observation.centroid.y - self.center_y) / self.radius_y
        return math.hypot(dx, dy)

    def pixel_distance(self, observation: TrackObservation) -> float:
        return math.hypot(observation.centroid.x - self.center_x, observation.centroid.y - self.center_y)


@dataclass(frozen=True, slots=True)
class _TerminalDecision:
    terminal: ShotLifecycleTerminal
    timestamp_seconds: float
    evidence: ShotLifecycleEvidence
    event_kind: ShotLifecycleEventKind
    state: ShotLifecycleState
    result_score: float


class ShotLifecycleService:
    """Convert associated ball/player/rim evidence into released-shot attempts."""

    def __init__(self, *, config: ShotLifecycleConfig | None = None) -> None:
        self._config = config or ShotLifecycleConfig()

    def detect(
        self,
        *,
        analysis_run_id: str,
        segments: Sequence[CameraSegment],
        observations: Sequence[TrackObservation],
        possession_frames: Sequence[PossessionFrame],
        calibrations: Sequence[Calibration] = (),
    ) -> ShotLifecycleResult:
        """Detect lifecycle-complete automatic shot attempts for stable camera segments."""

        stable_segments = tuple(
            sorted(
                (segment for segment in segments if segment.stability_status.upper() == "STABLE"),
                key=lambda item: (item.start_seconds, item.id),
            )
        )
        possession_by_ball_id = {frame.ball_observation_id: frame for frame in possession_frames}
        rims = _rim_targets(observations, calibrations)
        candidates: list[ShotAttemptCandidate] = []
        ignored: list[IgnoredReleaseCandidate] = []

        for segment in stable_segments:
            segment_observations = tuple(
                sorted(
                    (
                        item
                        for item in observations
                        if item.segment_id == segment.id
                        and segment.start_seconds <= item.timestamp_seconds < segment.end_seconds
                    ),
                    key=_observation_key,
                )
            )
            segment_balls = tuple(
                item
                for item in segment_observations
                if item.object_class is TrackedObjectClass.BASKETBALL and item.visibility is not VisibilityState.LOST
            )
            if not segment_balls:
                continue
            segment_rims = rims.get(segment.id, ())
            detected, skipped = self._detect_segment(
                analysis_run_id=analysis_run_id,
                segment=segment,
                ball_observations=segment_balls,
                possession_by_ball_id=possession_by_ball_id,
                rim_targets=segment_rims,
            )
            candidates.extend(detected)
            ignored.extend(skipped)

        return ShotLifecycleResult(
            candidates=tuple(sorted(candidates, key=lambda item: (item.release_seconds, item.id))),
            ignored_releases=tuple(
                sorted(ignored, key=lambda item: (item.timestamp_seconds, item.ball_observation_id))
            ),
        )

    def _detect_segment(
        self,
        *,
        analysis_run_id: str,
        segment: CameraSegment,
        ball_observations: Sequence[TrackObservation],
        possession_by_ball_id: dict[str, PossessionFrame],
        rim_targets: Sequence[_RimTarget],
    ) -> tuple[list[ShotAttemptCandidate], list[IgnoredReleaseCandidate]]:
        candidates: list[ShotAttemptCandidate] = []
        ignored: list[IgnoredReleaseCandidate] = []
        possession_run: list[PossessionFrame] = []
        possession_owner: str | None = None
        suppress_until = -1.0
        index = 0
        while index < len(ball_observations):
            ball = ball_observations[index]
            frame = possession_by_ball_id.get(ball.id)
            owner = _clear_possession_owner(frame)
            if ball.timestamp_seconds <= suppress_until:
                index += 1
                continue
            if owner is not None:
                if owner == possession_owner:
                    if frame is not None:
                        possession_run.append(frame)
                else:
                    possession_owner = owner
                    possession_run = [frame] if frame is not None else []
                index += 1
                continue

            if possession_owner is None or not possession_run:
                index += 1
                continue

            if len(possession_run) < self._config.minimum_possession_frames:
                ignored.append(
                    _ignored_release(
                        segment.id,
                        ball,
                        possession_owner,
                        IgnoredReleaseReason.INSUFFICIENT_POSSESSION,
                        possession_run,
                    )
                )
                possession_owner = None
                possession_run = []
                index += 1
                continue

            release_elapsed = ball.timestamp_seconds - possession_run[-1].timestamp_seconds
            if release_elapsed > self._config.release_window_seconds:
                ignored.append(
                    _ignored_release(
                        segment.id,
                        ball,
                        possession_owner,
                        IgnoredReleaseReason.RELEASE_WINDOW_EXPIRED,
                        possession_run,
                    )
                )
                possession_owner = None
                possession_run = []
                index += 1
                continue

            candidate = self._evaluate_release(
                analysis_run_id=analysis_run_id,
                segment=segment,
                release_index=index,
                shooter_track_id=possession_owner,
                possession_run=tuple(possession_run),
                ball_observations=ball_observations,
                possession_by_ball_id=possession_by_ball_id,
                rim_targets=rim_targets,
            )
            if candidate is None:
                ignored.append(
                    _ignored_release(
                        segment.id,
                        ball,
                        possession_owner,
                        IgnoredReleaseReason.NOT_SHOT_MOTION,
                        possession_run,
                    )
                )
                possession_owner = None
                possession_run = []
                index += 1
                continue

            candidates.append(candidate)
            suppress_until = candidate.result_end_seconds
            possession_owner = None
            possession_run = []
            index += 1
        return candidates, ignored

    def _evaluate_release(
        self,
        *,
        analysis_run_id: str,
        segment: CameraSegment,
        release_index: int,
        shooter_track_id: str,
        possession_run: tuple[PossessionFrame, ...],
        ball_observations: Sequence[TrackObservation],
        possession_by_ball_id: dict[str, PossessionFrame],
        rim_targets: Sequence[_RimTarget],
    ) -> ShotAttemptCandidate | None:
        release = ball_observations[release_index]
        previous_ball_id = possession_run[-1].ball_observation_id
        flight = tuple(
            item
            for item in ball_observations[release_index:]
            if item.timestamp_seconds - release.timestamp_seconds <= self._config.uncertainty_timeout_seconds
        )
        rim = _nearest_rim(rim_targets, release.timestamp_seconds)
        if not self._has_shot_intent(release, flight, rim):
            return None

        possession_evidence = ShotLifecycleEvidence(
            kind=ShotLifecycleEvidenceKind.POSSESSION,
            timestamp_seconds=possession_run[-1].timestamp_seconds,
            observation_ids=tuple(dict.fromkeys(frame.ball_observation_id for frame in possession_run[-3:])),
            description="Ball was possessed by one associated shooter before release.",
        )
        release_evidence = ShotLifecycleEvidence(
            kind=ShotLifecycleEvidenceKind.RELEASE,
            timestamp_seconds=release.timestamp_seconds,
            observation_ids=tuple(dict.fromkeys((previous_ball_id, release.id))),
            description="Ball separated from the associated shooter.",
        )
        flight_evidence = ShotLifecycleEvidence(
            kind=ShotLifecycleEvidenceKind.FLIGHT,
            timestamp_seconds=release.timestamp_seconds,
            observation_ids=tuple(item.id for item in flight),
            description="Free-flight basketball observations after release.",
        )
        events = [
            ShotLifecycleEvent(
                ShotLifecycleEventKind.POSSESSION_ENTERED,
                ShotLifecycleState.POSSESSED,
                possession_run[0].timestamp_seconds,
                possession_evidence,
            ),
            ShotLifecycleEvent(
                ShotLifecycleEventKind.RELEASE_DETECTED,
                ShotLifecycleState.RELEASED,
                release.timestamp_seconds,
                release_evidence,
            ),
            ShotLifecycleEvent(
                ShotLifecycleEventKind.FREE_FLIGHT_OBSERVED,
                ShotLifecycleState.FLIGHT,
                release.timestamp_seconds,
                flight_evidence,
            ),
        ]
        terminal = self._terminal_decision(
            release=release,
            flight=flight,
            shooter_track_id=shooter_track_id,
            possession_by_ball_id=possession_by_ball_id,
            rim=rim,
        )
        events.append(
            ShotLifecycleEvent(terminal.event_kind, terminal.state, terminal.timestamp_seconds, terminal.evidence)
        )
        evidence = [possession_evidence, release_evidence, flight_evidence, terminal.evidence]
        if rim is not None:
            evidence.append(
                ShotLifecycleEvidence(
                    kind=rim.source,
                    timestamp_seconds=release.timestamp_seconds,
                    observation_ids=(rim.evidence_id,),
                    description="Rim geometry used for approach and interaction windows.",
                )
            )
        confidence = _confidence(possession_run, flight, terminal.result_score)
        candidate_id = str(
            uuid5(
                NAMESPACE_URL,
                (
                    f"shotsight:{analysis_run_id}:shot-lifecycle:{segment.id}:"
                    f"{release.frame_index}:{release.id}:{terminal.terminal.value}"
                ),
            )
        )
        return ShotAttemptCandidate(
            id=candidate_id,
            analysis_run_id=analysis_run_id,
            segment_id=segment.id,
            shooter_track_id=shooter_track_id,
            release_seconds=release.timestamp_seconds,
            release_frame_index=release.frame_index,
            release_observation_id=release.id,
            result_start_seconds=release.timestamp_seconds,
            result_end_seconds=terminal.timestamp_seconds,
            terminal=terminal.terminal,
            confidence=confidence,
            evidence=tuple(evidence),
            events=tuple(events),
        )

    def _terminal_decision(
        self,
        *,
        release: TrackObservation,
        flight: tuple[TrackObservation, ...],
        shooter_track_id: str,
        possession_by_ball_id: dict[str, PossessionFrame],
        rim: _RimTarget | None,
    ) -> _TerminalDecision:
        approach_evidence: ShotLifecycleEvidence | None = None
        for ball in flight[1:]:
            elapsed = ball.timestamp_seconds - release.timestamp_seconds
            frame = possession_by_ball_id.get(ball.id)
            if elapsed <= self._config.immediate_block_seconds and _blocked_by_non_shooter(
                frame,
                shooter_track_id,
                self._config.block_candidate_normalized_distance,
            ):
                evidence = ShotLifecycleEvidence(
                    kind=ShotLifecycleEvidenceKind.BLOCK,
                    timestamp_seconds=ball.timestamp_seconds,
                    observation_ids=_block_evidence_ids(ball, frame),
                    description="Released ball was immediately interrupted by a non-shooter player.",
                )
                return _TerminalDecision(
                    ShotLifecycleTerminal.BLOCKED,
                    ball.timestamp_seconds,
                    evidence,
                    ShotLifecycleEventKind.IMMEDIATE_BLOCK_DETECTED,
                    ShotLifecycleState.IMMEDIATE_BLOCK,
                    _frame_score(frame, fallback=ball.confidence * 0.75),
                )

            if rim is not None:
                rim_distance = rim.normalized_distance(ball)
                if rim_distance <= self._config.rim_approach_radius_multiplier and approach_evidence is None:
                    approach_evidence = ShotLifecycleEvidence(
                        kind=ShotLifecycleEvidenceKind.RIM,
                        timestamp_seconds=ball.timestamp_seconds,
                        observation_ids=(ball.id, rim.evidence_id),
                        description="Released ball entered the rim approach window.",
                    )
                if rim_distance <= self._config.rim_interaction_radius_multiplier:
                    evidence = ShotLifecycleEvidence(
                        kind=ShotLifecycleEvidenceKind.RESULT,
                        timestamp_seconds=ball.timestamp_seconds,
                        observation_ids=(ball.id, rim.evidence_id),
                        description="Released ball entered the rim interaction window.",
                    )
                    return _TerminalDecision(
                        ShotLifecycleTerminal.RIM_INTERACTION,
                        ball.timestamp_seconds,
                        evidence,
                        ShotLifecycleEventKind.RIM_INTERACTION_DETECTED,
                        ShotLifecycleState.RIM_INTERACTION,
                        min(1.0, (ball.confidence + rim.confidence) / 2),
                    )

        if rim is not None and _airball_completed(flight, release, self._config):
            final = flight[-1]
            evidence_ids: tuple[str, ...] = (final.id, rim.evidence_id)
            if approach_evidence is not None:
                evidence_ids = tuple(dict.fromkeys((*approach_evidence.observation_ids, *evidence_ids)))
            evidence = ShotLifecycleEvidence(
                kind=ShotLifecycleEvidenceKind.RESULT,
                timestamp_seconds=final.timestamp_seconds,
                observation_ids=evidence_ids,
                description="Released ball completed away from the rim interaction window.",
            )
            return _TerminalDecision(
                ShotLifecycleTerminal.AIR_BALL,
                final.timestamp_seconds,
                evidence,
                ShotLifecycleEventKind.AIR_BALL_DETECTED,
                ShotLifecycleState.AIR_BALL,
                min(0.85, (final.confidence + rim.confidence) / 2),
            )

        final = flight[-1]
        evidence = ShotLifecycleEvidence(
            kind=ShotLifecycleEvidenceKind.RESULT,
            timestamp_seconds=final.timestamp_seconds,
            observation_ids=(final.id,),
            description="Released shot reached bounded uncertainty before a terminal interaction was observed.",
        )
        return _TerminalDecision(
            ShotLifecycleTerminal.UNCERTAIN,
            final.timestamp_seconds,
            evidence,
            ShotLifecycleEventKind.UNCERTAINTY_TIMEOUT,
            ShotLifecycleState.UNCERTAIN,
            min(0.45, final.confidence * 0.5),
        )

    def _has_shot_intent(
        self,
        release: TrackObservation,
        flight: tuple[TrackObservation, ...],
        rim: _RimTarget | None,
    ) -> bool:
        window = tuple(
            item
            for item in flight
            if item.timestamp_seconds - release.timestamp_seconds <= self._config.shot_intent_window_seconds
        )
        if len(window) < 2:
            return False
        upward_pixels = release.centroid.y - min(item.centroid.y for item in window)
        if upward_pixels >= self._config.minimum_upward_pixels:
            return True
        if rim is None:
            return False
        release_distance = rim.pixel_distance(release)
        best_distance = min(rim.pixel_distance(item) for item in window)
        if release_distance <= max(rim.radius_x, rim.radius_y) * self._config.rim_approach_radius_multiplier:
            return True
        return release_distance - best_distance >= self._config.minimum_rim_approach_pixels


def _rim_targets(
    observations: Sequence[TrackObservation],
    calibrations: Sequence[Calibration],
) -> dict[str, tuple[_RimTarget, ...]]:
    by_segment: dict[str, list[_RimTarget]] = {}
    latest_calibrations: dict[str, Calibration] = {}
    for calibration in calibrations:
        current = latest_calibrations.get(calibration.segment_id)
        if current is None or (calibration.created_at, calibration.id) > (current.created_at, current.id):
            latest_calibrations[calibration.segment_id] = calibration
    for calibration in latest_calibrations.values():
        geometry = calibration_geometry_from_json(calibration.rim_geometry, calibration.court_points)
        if geometry.rim is None:
            continue
        by_segment.setdefault(calibration.segment_id, []).append(
            _target_from_rim(calibration.segment_id, geometry.rim, calibration.id)
        )

    for observation in observations:
        if observation.object_class is not TrackedObjectClass.RIM or observation.visibility is VisibilityState.LOST:
            continue
        by_segment.setdefault(observation.segment_id, []).append(_target_from_observation(observation))
    return {
        segment_id: tuple(sorted(items, key=lambda item: (item.source.value, item.evidence_id)))
        for segment_id, items in by_segment.items()
    }


def _target_from_rim(segment_id: str, rim: RimGeometry, evidence_id: str) -> _RimTarget:
    return _RimTarget(
        segment_id=segment_id,
        center_x=rim.center.x,
        center_y=rim.center.y,
        radius_x=rim.radius_x,
        radius_y=rim.radius_y,
        confidence=rim.confidence,
        evidence_id=evidence_id,
        source=ShotLifecycleEvidenceKind.CALIBRATION,
    )


def _target_from_observation(observation: TrackObservation) -> _RimTarget:
    box = observation.bounding_box
    return _RimTarget(
        segment_id=observation.segment_id,
        center_x=observation.centroid.x,
        center_y=observation.centroid.y,
        radius_x=max(1.0, box.width / 2),
        radius_y=max(1.0, box.height / 2),
        confidence=observation.confidence,
        evidence_id=observation.id,
        source=ShotLifecycleEvidenceKind.RIM,
    )


def _nearest_rim(rims: Sequence[_RimTarget], timestamp_seconds: float) -> _RimTarget | None:
    del timestamp_seconds
    return rims[0] if rims else None


def _clear_possession_owner(frame: PossessionFrame | None) -> str | None:
    if frame is None or frame.confidence.ambiguous:
        return None
    return frame.player_track_id


def _blocked_by_non_shooter(
    frame: PossessionFrame | None,
    shooter_track_id: str,
    block_candidate_normalized_distance: float,
) -> bool:
    if frame is None:
        return False
    if (
        frame.player_track_id is not None
        and frame.player_track_id != shooter_track_id
        and not frame.confidence.ambiguous
    ):
        return True
    return any(
        candidate.player_track_id != shooter_track_id
        and candidate.normalized_distance <= block_candidate_normalized_distance
        for candidate in frame.candidates
    )


def _block_evidence_ids(ball: TrackObservation, frame: PossessionFrame | None) -> tuple[str, ...]:
    if frame is None:
        return (ball.id,)
    return tuple(
        dict.fromkeys(
            (
                ball.id,
                frame.ball_observation_id,
                *(candidate.player_observation_id for candidate in frame.candidates),
            )
        )
    )


def _airball_completed(
    flight: tuple[TrackObservation, ...],
    release: TrackObservation,
    config: ShotLifecycleConfig,
) -> bool:
    if len(flight) < 3:
        return False
    final = flight[-1]
    if final.timestamp_seconds - release.timestamp_seconds < config.airball_minimum_flight_seconds:
        return False
    highest_y = min(item.centroid.y for item in flight)
    return final.centroid.y - highest_y >= config.descent_pixels_for_airball


def _confidence(
    possession_run: tuple[PossessionFrame, ...],
    flight: tuple[TrackObservation, ...],
    result_score: float,
) -> ShotLifecycleConfidence:
    release_score = min(possession_run[-1].confidence.score, flight[0].confidence)
    flight_score = sum(item.confidence for item in flight) / len(flight)
    score = _clamp((release_score * 0.4) + (flight_score * 0.25) + (result_score * 0.35))
    return ShotLifecycleConfidence(
        score=score,
        release_score=_clamp(release_score),
        flight_score=_clamp(flight_score),
        result_score=_clamp(result_score),
        reasons=(
            "Possession preceded release.",
            "Ball separated into free flight.",
            "Lifecycle terminal type was detected before timeout.",
        ),
    )


def _frame_score(frame: PossessionFrame | None, *, fallback: float) -> float:
    if frame is None:
        return _clamp(fallback)
    return _clamp(max(frame.confidence.score, fallback))


def _ignored_release(
    segment_id: str,
    ball: TrackObservation,
    shooter_track_id: str | None,
    reason: IgnoredReleaseReason,
    possession_run: Sequence[PossessionFrame],
) -> IgnoredReleaseCandidate:
    evidence_ids = tuple(dict.fromkeys((*[frame.ball_observation_id for frame in possession_run[-3:]], ball.id)))
    return IgnoredReleaseCandidate(
        segment_id=segment_id,
        timestamp_seconds=ball.timestamp_seconds,
        ball_observation_id=ball.id,
        shooter_track_id=shooter_track_id,
        reason=reason,
        evidence_observation_ids=evidence_ids,
    )


def _observation_key(observation: TrackObservation) -> tuple[float, int, str, str]:
    return (observation.timestamp_seconds, observation.frame_index, observation.local_track_id, observation.id)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def rim_geometry(center_x: float, center_y: float, radius_x: float, radius_y: float, confidence: float) -> RimGeometry:
    """Build calibration rim geometry for deterministic tests and adapters."""

    return RimGeometry(CalibrationImagePoint(center_x, center_y), radius_x, radius_y, confidence)
