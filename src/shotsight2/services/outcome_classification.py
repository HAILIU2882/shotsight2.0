"""Conservative automatic make/miss classification over shot lifecycle candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from shotsight2.domain.calibration import calibration_geometry_from_json
from shotsight2.domain.outcome import (
    OutcomeClassification,
    OutcomeConfidence,
    OutcomeEvidence,
    OutcomeEvidenceKind,
    RimCrossingVolume,
)
from shotsight2.domain.persistence import Calibration, JsonValue, ShotAttempt, ShotOutcome
from shotsight2.domain.shot_lifecycle import ShotAttemptCandidate, ShotLifecycleTerminal
from shotsight2.domain.tracking import TrackedObjectClass, TrackObservation, VisibilityState


@dataclass(frozen=True, slots=True)
class OutcomeClassificationConfig:
    """Thresholds for deterministic image-space outcome classification."""

    post_result_window_seconds: float = 1.0
    minimum_downward_pixels: float = 2.0
    below_rim_margin_pixels: float = 2.0
    below_rim_horizontal_multiplier: float = 1.25
    rim_near_distance_multiplier: float = 2.0
    maximum_required_tracking_gap_seconds: float = 0.35

    def __post_init__(self) -> None:
        values = (
            self.post_result_window_seconds,
            self.minimum_downward_pixels,
            self.below_rim_margin_pixels,
            self.below_rim_horizontal_multiplier,
            self.rim_near_distance_multiplier,
            self.maximum_required_tracking_gap_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Outcome classification thresholds must be positive")


@dataclass(frozen=True, slots=True)
class OutcomeClassificationResult:
    """Outcome classification output for one analysis run."""

    classifications: tuple[OutcomeClassification, ...]
    attempts: tuple[ShotAttempt, ...]


class OutcomeClassificationService:
    """Classify automatic shot outcomes without mutating lifecycle decisions."""

    def __init__(self, *, config: OutcomeClassificationConfig | None = None) -> None:
        self._config = config or OutcomeClassificationConfig()

    def classify(
        self,
        *,
        candidates: Sequence[ShotAttemptCandidate],
        observations: Sequence[TrackObservation],
        calibrations: Sequence[Calibration],
    ) -> OutcomeClassificationResult:
        """Classify lifecycle candidates and return persistence-ready attempts."""

        volumes = _rim_volumes(calibrations)
        classifications: list[OutcomeClassification] = []
        attempts: list[ShotAttempt] = []
        balls_by_segment = _basketballs_by_segment(observations)
        for candidate in candidates:
            ball_path = _candidate_ball_path(
                candidate,
                balls_by_segment.get(candidate.segment_id, ()),
                post_result_window_seconds=self._config.post_result_window_seconds,
            )
            classification = self._classify_candidate(
                candidate,
                ball_path,
                volumes.get(candidate.segment_id),
            )
            classifications.append(classification)
            attempts.append(_classified_attempt(candidate, classification))
        return OutcomeClassificationResult(
            classifications=tuple(classifications),
            attempts=tuple(attempts),
        )

    def _classify_candidate(
        self,
        candidate: ShotAttemptCandidate,
        ball_path: tuple[TrackObservation, ...],
        rim: RimCrossingVolume | None,
    ) -> OutcomeClassification:
        if candidate.terminal is ShotLifecycleTerminal.BLOCKED:
            return _completed_miss(
                candidate,
                OutcomeEvidenceKind.BLOCKED_SHOT,
                "Released ball was blocked after leaving the shooter.",
            )
        if candidate.terminal is ShotLifecycleTerminal.AIR_BALL:
            return _completed_miss(
                candidate,
                OutcomeEvidenceKind.AIR_BALL,
                "Released ball completed away from the calibrated rim volume.",
            )
        if candidate.terminal is ShotLifecycleTerminal.UNCERTAIN:
            return _uncertain(
                candidate,
                OutcomeEvidence(
                    OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE,
                    candidate.result_end_seconds,
                    (candidate.release_observation_id,),
                    "Shot lifecycle ended before sufficient outcome evidence was visible.",
                ),
                rim,
            )
        if rim is None:
            return _uncertain(
                candidate,
                OutcomeEvidence(
                    OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE,
                    candidate.release_seconds,
                    (candidate.release_observation_id,),
                    "No calibrated rim volume was available for make/miss classification.",
                ),
                None,
            )
        volume_evidence = OutcomeEvidence(
            OutcomeEvidenceKind.RIM_VOLUME,
            candidate.release_seconds,
            (rim.evidence_id,),
            "Calibrated image-space rim volume used for outcome classification.",
        )
        required_visibility_issue = self._required_visibility_issue(ball_path, rim, candidate)
        if required_visibility_issue is not None:
            return _uncertain(candidate, required_visibility_issue, rim, extra_evidence=(volume_evidence,))

        entry = self._downward_entry(ball_path, rim)
        if entry is not None:
            continuation = self._below_rim_continuation(ball_path, rim, after_seconds=entry.timestamp_seconds)
            if continuation is not None:
                entry_evidence = OutcomeEvidence(
                    OutcomeEvidenceKind.DOWNWARD_ENTRY,
                    entry.timestamp_seconds,
                    entry.observation_ids,
                    "Ball entered the calibrated rim volume while moving downward.",
                )
                continuation_evidence = OutcomeEvidence(
                    OutcomeEvidenceKind.BELOW_RIM_CONTINUATION,
                    continuation.timestamp_seconds,
                    continuation.observation_ids,
                    "Ball continued below the rim after downward entry.",
                )
                return _made(candidate, rim, volume_evidence, entry_evidence, continuation_evidence)
            missing = OutcomeEvidence(
                OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE,
                entry.timestamp_seconds,
                entry.observation_ids,
                "Downward rim entry was visible, but below-rim continuation was not observed.",
            )
            if _path_stops_near_rim(ball_path, rim):
                return _uncertain(candidate, missing, rim, extra_evidence=(volume_evidence,))

        rim_exit = self._visible_rim_exit(ball_path, rim)
        if rim_exit is not None:
            return _visible_miss(candidate, rim, volume_evidence, rim_exit)

        insufficient = OutcomeEvidence(
            OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE,
            candidate.result_end_seconds,
            (candidate.release_observation_id,),
            "Rim interaction lacked clear downward crossing or visible non-crossing exit evidence.",
        )
        return _uncertain(candidate, insufficient, rim, extra_evidence=(volume_evidence,))

    def _required_visibility_issue(
        self,
        ball_path: tuple[TrackObservation, ...],
        rim: RimCrossingVolume,
        candidate: ShotAttemptCandidate,
    ) -> OutcomeEvidence | None:
        if not ball_path:
            return OutcomeEvidence(
                OutcomeEvidenceKind.INSUFFICIENT_EVIDENCE,
                candidate.release_seconds,
                (candidate.release_observation_id,),
                "No ball observations were available during the outcome window.",
            )
        near_rim = [item for item in ball_path if rim.normalized_distance(item.centroid.x, item.centroid.y) <= 1.5]
        for item in near_rim:
            if item.visibility is VisibilityState.OCCLUDED or item.occluded:
                return OutcomeEvidence(
                    OutcomeEvidenceKind.OCCLUSION,
                    item.timestamp_seconds,
                    (item.id, rim.evidence_id),
                    "Required rim-crossing evidence was occluded.",
                )
            if item.visibility is VisibilityState.LOST:
                return OutcomeEvidence(
                    OutcomeEvidenceKind.TRACKING_LOSS,
                    item.timestamp_seconds,
                    (item.id, rim.evidence_id),
                    "Ball tracking was lost while outcome evidence was required.",
                )

        approach_started = False
        for previous, current in zip(ball_path, ball_path[1:], strict=False):
            previous_near = rim.normalized_distance(previous.centroid.x, previous.centroid.y)
            current_near = rim.normalized_distance(current.centroid.x, current.centroid.y)
            if min(previous_near, current_near) <= self._config.rim_near_distance_multiplier:
                approach_started = True
            if (
                approach_started
                and current.timestamp_seconds - previous.timestamp_seconds
                > self._config.maximum_required_tracking_gap_seconds
            ):
                return OutcomeEvidence(
                    OutcomeEvidenceKind.TRACKING_LOSS,
                    previous.timestamp_seconds,
                    (previous.id, current.id, rim.evidence_id),
                    "Ball track had a gap while rim-crossing evidence was required.",
                )
        return None

    def _downward_entry(
        self,
        ball_path: tuple[TrackObservation, ...],
        rim: RimCrossingVolume,
    ) -> _OutcomeTransition | None:
        for previous, current in zip(ball_path, ball_path[1:], strict=False):
            if current.visibility is VisibilityState.LOST or previous.visibility is VisibilityState.LOST:
                continue
            current_inside = rim.contains(current.centroid.x, current.centroid.y)
            if not current_inside:
                continue
            downward = current.centroid.y - previous.centroid.y >= self._config.minimum_downward_pixels
            entered_from_above = (
                previous.centroid.y <= rim.center_y and current.centroid.y >= rim.center_y - rim.radius_y
            )
            if downward and entered_from_above:
                return _OutcomeTransition(
                    current.timestamp_seconds,
                    tuple(dict.fromkeys((previous.id, current.id, rim.evidence_id))),
                    min(previous.confidence, current.confidence, rim.confidence),
                )
        return None

    def _below_rim_continuation(
        self,
        ball_path: tuple[TrackObservation, ...],
        rim: RimCrossingVolume,
        *,
        after_seconds: float,
    ) -> _OutcomeTransition | None:
        for item in ball_path:
            if item.timestamp_seconds <= after_seconds:
                continue
            if item.visibility is VisibilityState.LOST:
                continue
            if rim.below_rim(
                item.centroid.x,
                item.centroid.y,
                margin_pixels=self._config.below_rim_margin_pixels,
                horizontal_multiplier=self._config.below_rim_horizontal_multiplier,
            ):
                return _OutcomeTransition(
                    item.timestamp_seconds,
                    (item.id, rim.evidence_id),
                    min(item.confidence, rim.confidence),
                )
        return None

    def _visible_rim_exit(
        self,
        ball_path: tuple[TrackObservation, ...],
        rim: RimCrossingVolume,
    ) -> OutcomeEvidence | None:
        entered_near_rim = False
        evidence_ids: list[str] = [rim.evidence_id]
        for item in ball_path:
            distance = rim.normalized_distance(item.centroid.x, item.centroid.y)
            if distance <= self._config.rim_near_distance_multiplier:
                entered_near_rim = True
                evidence_ids.append(item.id)
                continue
            if entered_near_rim and item.timestamp_seconds > ball_path[0].timestamp_seconds:
                evidence_ids.append(item.id)
                return OutcomeEvidence(
                    OutcomeEvidenceKind.RIM_EXIT,
                    item.timestamp_seconds,
                    tuple(dict.fromkeys(evidence_ids[-5:])),
                    "Visible rim interaction exited without a valid downward crossing and continuation.",
                )
        return None


@dataclass(frozen=True, slots=True)
class _OutcomeTransition:
    timestamp_seconds: float
    observation_ids: tuple[str, ...]
    score: float


def _rim_volumes(calibrations: Sequence[Calibration]) -> dict[str, RimCrossingVolume]:
    latest: dict[str, Calibration] = {}
    for calibration in calibrations:
        current = latest.get(calibration.segment_id)
        if current is None or (calibration.created_at, calibration.id) > (current.created_at, current.id):
            latest[calibration.segment_id] = calibration
    volumes: dict[str, RimCrossingVolume] = {}
    for calibration in latest.values():
        geometry = calibration_geometry_from_json(calibration.rim_geometry, calibration.court_points)
        if geometry.rim is None:
            continue
        rim = geometry.rim
        volumes[calibration.segment_id] = RimCrossingVolume(
            segment_id=calibration.segment_id,
            center_x=rim.center.x,
            center_y=rim.center.y,
            radius_x=rim.radius_x,
            radius_y=rim.radius_y,
            confidence=min(calibration.confidence, rim.confidence),
            evidence_id=calibration.id,
        )
    return volumes


def _basketballs_by_segment(
    observations: Sequence[TrackObservation],
) -> dict[str, tuple[TrackObservation, ...]]:
    grouped: dict[str, list[TrackObservation]] = {}
    for observation in observations:
        if observation.object_class is TrackedObjectClass.BASKETBALL:
            grouped.setdefault(observation.segment_id, []).append(observation)
    return {
        segment_id: tuple(sorted(items, key=lambda item: (item.timestamp_seconds, item.frame_index, item.id)))
        for segment_id, items in grouped.items()
    }


def _candidate_ball_path(
    candidate: ShotAttemptCandidate,
    observations: Sequence[TrackObservation],
    *,
    post_result_window_seconds: float,
) -> tuple[TrackObservation, ...]:
    end_seconds = candidate.result_end_seconds + post_result_window_seconds
    return tuple(
        item
        for item in observations
        if candidate.release_seconds <= item.timestamp_seconds <= end_seconds
        and item.local_track_id == _release_track_id(candidate, observations)
    )


def _release_track_id(candidate: ShotAttemptCandidate, observations: Sequence[TrackObservation]) -> str:
    for item in observations:
        if item.id == candidate.release_observation_id:
            return item.local_track_id
    return observations[0].local_track_id if observations else ""


def _classified_attempt(candidate: ShotAttemptCandidate, classification: OutcomeClassification) -> ShotAttempt:
    attempt = candidate.to_shot_attempt()
    evidence = dict(attempt.evidence)
    evidence["automatic_outcome_deferred"] = False
    evidence["outcome_classification"] = cast(JsonValue, classification.to_json())
    evidence["automatic_outcome"] = classification.outcome.value
    evidence["outcome_confidence"] = classification.confidence.to_json()
    return ShotAttempt(
        id=attempt.id,
        analysis_run_id=attempt.analysis_run_id,
        shooter_track_id=attempt.shooter_track_id,
        release_seconds=attempt.release_seconds,
        automatic_outcome=classification.outcome,
        shot_type=attempt.shot_type,
        confidence=classification.confidence.score,
        review_status=attempt.review_status,
        evidence=evidence,
        manual=attempt.manual,
    )


def _completed_miss(
    candidate: ShotAttemptCandidate,
    kind: OutcomeEvidenceKind,
    description: str,
) -> OutcomeClassification:
    evidence = OutcomeEvidence(
        kind,
        candidate.result_end_seconds,
        (candidate.release_observation_id,),
        description,
    )
    terminal_score = candidate.confidence.result_score
    confidence = OutcomeConfidence(
        score=_clamp((candidate.confidence.score * 0.5) + (terminal_score * 0.5)),
        crossing_score=0.0,
        continuation_score=0.0,
        visibility_score=terminal_score,
        reasons=("Completed non-made terminal lifecycle was observed.",),
    )
    return OutcomeClassification(ShotOutcome.MISSED, confidence, (evidence,), None)


def _visible_miss(
    candidate: ShotAttemptCandidate,
    rim: RimCrossingVolume,
    volume_evidence: OutcomeEvidence,
    rim_exit: OutcomeEvidence,
) -> OutcomeClassification:
    confidence = OutcomeConfidence(
        score=_clamp((candidate.confidence.score * 0.4) + (rim.confidence * 0.3) + 0.25),
        crossing_score=0.0,
        continuation_score=0.0,
        visibility_score=min(candidate.confidence.flight_score, rim.confidence),
        reasons=("Visible rim interaction did not show downward crossing and below-rim continuation.",),
    )
    return OutcomeClassification(ShotOutcome.MISSED, confidence, (volume_evidence, rim_exit), rim)


def _made(
    candidate: ShotAttemptCandidate,
    rim: RimCrossingVolume,
    volume_evidence: OutcomeEvidence,
    entry_evidence: OutcomeEvidence,
    continuation_evidence: OutcomeEvidence,
) -> OutcomeClassification:
    crossing_score = min(candidate.confidence.flight_score, rim.confidence)
    continuation_score = min(candidate.confidence.result_score, rim.confidence)
    score = _clamp(
        (candidate.confidence.release_score * 0.15)
        + (crossing_score * 0.4)
        + (continuation_score * 0.3)
        + (rim.confidence * 0.15)
    )
    confidence = OutcomeConfidence(
        score=score,
        crossing_score=crossing_score,
        continuation_score=continuation_score,
        visibility_score=min(candidate.confidence.flight_score, rim.confidence),
        reasons=("Downward rim entry and below-rim continuation were observed.",),
    )
    return OutcomeClassification(
        ShotOutcome.MADE,
        confidence,
        (volume_evidence, entry_evidence, continuation_evidence),
        rim,
    )


def _uncertain(
    candidate: ShotAttemptCandidate,
    evidence: OutcomeEvidence,
    rim: RimCrossingVolume | None,
    *,
    extra_evidence: tuple[OutcomeEvidence, ...] = (),
) -> OutcomeClassification:
    confidence = OutcomeConfidence(
        score=min(0.49, candidate.confidence.score * 0.5),
        crossing_score=0.0,
        continuation_score=0.0,
        visibility_score=min(0.49, candidate.confidence.flight_score * 0.5),
        reasons=("Required make/miss evidence was missing, occluded, or track-lost.",),
    )
    return OutcomeClassification(ShotOutcome.UNCERTAIN, confidence, (*extra_evidence, evidence), rim)


def _path_stops_near_rim(ball_path: tuple[TrackObservation, ...], rim: RimCrossingVolume) -> bool:
    if not ball_path:
        return True
    final = ball_path[-1]
    return rim.normalized_distance(final.centroid.x, final.centroid.y) <= 1.5


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
