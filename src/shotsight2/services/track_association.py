"""Deterministic player, possession, and shooter association service."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from shotsight2.domain.persistence import CameraSegment, PlayerTrack
from shotsight2.domain.track_association import (
    AssociationConfidence,
    AssociationDecision,
    AssociationEvidenceKind,
    AssociationEvidenceReference,
    LocalPlayerIdentity,
    PlayerObservationLink,
    PossessionCandidate,
    PossessionFrame,
    ReleaseEvent,
    ShooterAttribution,
)
from shotsight2.domain.tracking import BoundingBox, TrackedObjectClass, TrackObservation, VisibilityState


@dataclass(frozen=True, slots=True)
class TrackAssociationConfig:
    """Thresholds for deterministic local association."""

    adjacent_frame_gap_seconds: float = 0.25
    same_segment_max_distance_ratio: float = 0.6
    cross_segment_gap_seconds: float = 5.0
    cross_segment_max_distance_ratio: float = 0.9
    observation_alignment_seconds: float = 0.08
    possession_max_normalized_distance: float = 0.45
    possession_min_confidence: float = 0.35
    ambiguity_delta: float = 0.12
    possession_gap_seconds: float = 0.45
    release_window_seconds: float = 0.6

    def __post_init__(self) -> None:
        values = (
            self.adjacent_frame_gap_seconds,
            self.same_segment_max_distance_ratio,
            self.cross_segment_gap_seconds,
            self.cross_segment_max_distance_ratio,
            self.observation_alignment_seconds,
            self.possession_max_normalized_distance,
            self.possession_min_confidence,
            self.ambiguity_delta,
            self.possession_gap_seconds,
            self.release_window_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Association thresholds must be positive")
        if self.possession_min_confidence > 1 or self.ambiguity_delta > 1:
            raise ValueError("Possession confidence thresholds must be at most one")


@dataclass(frozen=True, slots=True)
class TrackAssociationResult:
    """Outputs produced by one association pass."""

    players: tuple[PlayerTrack, ...]
    identities: tuple[LocalPlayerIdentity, ...]
    observation_links: tuple[PlayerObservationLink, ...]
    possession_frames: tuple[PossessionFrame, ...]
    shooter_attributions: tuple[ShooterAttribution, ...]


@dataclass(slots=True)
class _SegmentTrack:
    observations: list[TrackObservation]
    source_local_track_ids: set[str] = field(default_factory=set)

    @property
    def first(self) -> TrackObservation:
        return self.observations[0]

    @property
    def last(self) -> TrackObservation:
        return self.observations[-1]

    @property
    def confidence(self) -> float:
        return sum(item.confidence for item in self.observations) / len(self.observations)


@dataclass(slots=True)
class _GlobalTrack:
    segment_tracks: list[_SegmentTrack]
    player_track_id: str = ""
    label: str = ""

    @property
    def first(self) -> TrackObservation:
        return self.segment_tracks[0].first

    @property
    def last(self) -> TrackObservation:
        return self.segment_tracks[-1].last

    @property
    def observations(self) -> Iterable[TrackObservation]:
        for segment_track in self.segment_tracks:
            yield from segment_track.observations

    @property
    def source_local_track_ids(self) -> tuple[str, ...]:
        values = {item for track in self.segment_tracks for item in track.source_local_track_ids}
        return tuple(sorted(values))

    @property
    def segment_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(track.first.segment_id for track in self.segment_tracks))

    @property
    def confidence(self) -> float:
        observations = tuple(self.observations)
        return sum(item.confidence for item in observations) / len(observations)


class TrackAssociationService:
    """Associate local player tracks, possession, and release ownership."""

    def __init__(self, *, config: TrackAssociationConfig | None = None) -> None:
        self._config = config or TrackAssociationConfig()

    def associate(
        self,
        *,
        analysis_run_id: str,
        video_id: str,
        segments: Sequence[CameraSegment],
        observations: Sequence[TrackObservation],
        release_events: Sequence[ReleaseEvent] = (),
    ) -> TrackAssociationResult:
        """Return deterministic local identities and release associations."""

        ordered_segments = tuple(sorted(segments, key=lambda item: (item.start_seconds, item.id)))
        player_observations = tuple(
            sorted(
                (item for item in observations if item.object_class is TrackedObjectClass.PLAYER),
                key=_observation_key,
            )
        )
        ball_observations = tuple(
            sorted(
                (item for item in observations if item.object_class is TrackedObjectClass.BASKETBALL),
                key=_observation_key,
            )
        )
        global_tracks = self._global_player_tracks(ordered_segments, player_observations)
        players, identities, links = self._materialize_players(analysis_run_id, video_id, global_tracks)
        possession_frames = self._possession_frames(ball_observations, player_observations, links)
        shooter_attributions = tuple(
            self._shooter_attribution(event, possession_frames) for event in sorted(release_events, key=_release_key)
        )
        return TrackAssociationResult(players, identities, links, possession_frames, shooter_attributions)

    def evidence_reference_for_shot(
        self,
        *,
        shot_attempt_id: str,
        analysis_run_id: str,
        attribution: ShooterAttribution,
    ) -> AssociationEvidenceReference:
        """Build a durable evidence reference for a lifecycle-owned shot attempt."""

        return AssociationEvidenceReference(
            id=str(uuid5(NAMESPACE_URL, f"shotsight:{analysis_run_id}:association-evidence:{shot_attempt_id}:shooter")),
            analysis_run_id=analysis_run_id,
            shot_attempt_id=shot_attempt_id,
            kind=AssociationEvidenceKind.SHOOTER,
            player_track_id=attribution.player_track_id,
            observation_ids=attribution.evidence_observation_ids,
            confidence=attribution.confidence.score,
            ambiguous=attribution.confidence.ambiguous,
            reason=attribution.confidence.reason,
        )

    def _global_player_tracks(
        self,
        segments: Sequence[CameraSegment],
        observations: Sequence[TrackObservation],
    ) -> list[_GlobalTrack]:
        observations_by_segment: dict[str, list[TrackObservation]] = defaultdict(list)
        for observation in observations:
            if observation.visibility is not VisibilityState.LOST:
                observations_by_segment[observation.segment_id].append(observation)

        global_tracks: list[_GlobalTrack] = []
        for segment in segments:
            segment_tracks = self._segment_player_tracks(observations_by_segment[segment.id])
            open_tracks = tuple(global_tracks)
            matched_globals: set[int] = set()
            for segment_track in segment_tracks:
                match = self._cross_segment_match(segment_track, open_tracks)
                if match is not None and id(match) in matched_globals:
                    match = None
                if match is None:
                    global_tracks.append(_GlobalTrack([segment_track]))
                else:
                    match.segment_tracks.append(segment_track)
                    matched_globals.add(id(match))
        return sorted(
            global_tracks, key=lambda item: (item.first.timestamp_seconds, item.first.centroid.x, item.first.id)
        )

    def _segment_player_tracks(self, observations: Sequence[TrackObservation]) -> list[_SegmentTrack]:
        by_frame: dict[int, list[TrackObservation]] = defaultdict(list)
        for observation in observations:
            by_frame[observation.frame_index].append(observation)

        active: list[_SegmentTrack] = []
        completed: list[_SegmentTrack] = []
        for frame_index in sorted(by_frame):
            frame_observations = sorted(
                by_frame[frame_index], key=lambda item: (item.local_track_id, item.centroid.x, item.id)
            )
            expired = [
                track
                for track in active
                if frame_observations[0].timestamp_seconds - track.last.timestamp_seconds
                > self._config.adjacent_frame_gap_seconds
            ]
            if expired:
                completed.extend(expired)
                active = [track for track in active if track not in expired]

            matches = self._same_segment_matches(active, frame_observations)
            matched_observations = {observation_index for _, observation_index in matches}
            for track_index, observation_index in matches:
                track = active[track_index]
                observation = frame_observations[observation_index]
                track.observations.append(observation)
                track.source_local_track_ids.add(observation.local_track_id)
            for observation_index, observation in enumerate(frame_observations):
                if observation_index not in matched_observations:
                    active.append(_SegmentTrack([observation], {observation.local_track_id}))

        return sorted(
            (*completed, *active), key=lambda item: (item.first.timestamp_seconds, item.first.centroid.x, item.first.id)
        )

    def _same_segment_matches(
        self,
        tracks: Sequence[_SegmentTrack],
        observations: Sequence[TrackObservation],
    ) -> list[tuple[int, int]]:
        pairs: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(tracks):
            for observation_index, observation in enumerate(observations):
                elapsed = observation.timestamp_seconds - track.last.timestamp_seconds
                if elapsed <= 0 or elapsed > self._config.adjacent_frame_gap_seconds:
                    continue
                ratio = _distance_ratio(track.last.bounding_box, observation.bounding_box)
                if ratio > self._config.same_segment_max_distance_ratio:
                    continue
                local_id_bonus = -0.25 if observation.local_track_id in track.source_local_track_ids else 0.0
                pairs.append((ratio + local_id_bonus, track_index, observation_index))

        result: list[tuple[int, int]] = []
        used_tracks: set[int] = set()
        used_observations: set[int] = set()
        for _, track_index, observation_index in sorted(pairs):
            if track_index in used_tracks or observation_index in used_observations:
                continue
            used_tracks.add(track_index)
            used_observations.add(observation_index)
            result.append((track_index, observation_index))
        return result

    def _cross_segment_match(
        self,
        segment_track: _SegmentTrack,
        global_tracks: Sequence[_GlobalTrack],
    ) -> _GlobalTrack | None:
        pairs: list[tuple[float, _GlobalTrack]] = []
        for global_track in global_tracks:
            elapsed = segment_track.first.timestamp_seconds - global_track.last.timestamp_seconds
            if elapsed <= 0 or elapsed > self._config.cross_segment_gap_seconds:
                continue
            ratio = _distance_ratio(global_track.last.bounding_box, segment_track.first.bounding_box)
            if ratio <= self._config.cross_segment_max_distance_ratio:
                pairs.append((ratio, global_track))
        if not pairs:
            return None
        return sorted(pairs, key=lambda item: (item[0], item[1].first.timestamp_seconds, item[1].first.id))[0][1]

    def _materialize_players(
        self,
        analysis_run_id: str,
        video_id: str,
        global_tracks: Sequence[_GlobalTrack],
    ) -> tuple[tuple[PlayerTrack, ...], tuple[LocalPlayerIdentity, ...], tuple[PlayerObservationLink, ...]]:
        players: list[PlayerTrack] = []
        identities: list[LocalPlayerIdentity] = []
        links: list[PlayerObservationLink] = []
        for index, global_track in enumerate(global_tracks, start=1):
            player_track_id = str(uuid5(NAMESPACE_URL, f"shotsight:{video_id}:{analysis_run_id}:player:{index}"))
            label = f"Player {index}"
            global_track.player_track_id = player_track_id
            global_track.label = label
            confidence = AssociationConfidence(
                _clamp(global_track.confidence),
                AssociationDecision.ASSOCIATED,
                "Linked by video-local track continuity and segment geometry.",
            )
            players.append(PlayerTrack(player_track_id, analysis_run_id, video_id, label, label, confidence.score))
            identities.append(
                LocalPlayerIdentity(
                    player_track_id,
                    analysis_run_id,
                    video_id,
                    label,
                    label,
                    confidence,
                    global_track.source_local_track_ids,
                    global_track.segment_ids,
                )
            )
            for observation in sorted(global_track.observations, key=_observation_key):
                links.append(
                    PlayerObservationLink(
                        observation.id,
                        observation.segment_id,
                        observation.frame_index,
                        observation.timestamp_seconds,
                        observation.local_track_id,
                        player_track_id,
                        confidence,
                    )
                )
        return (
            tuple(players),
            tuple(identities),
            tuple(sorted(links, key=lambda item: (item.timestamp_seconds, item.frame_index, item.observation_id))),
        )

    def _possession_frames(
        self,
        ball_observations: Sequence[TrackObservation],
        player_observations: Sequence[TrackObservation],
        links: Sequence[PlayerObservationLink],
    ) -> tuple[PossessionFrame, ...]:
        player_by_observation_id = {link.observation_id: link.player_track_id for link in links}
        player_by_segment: dict[str, list[TrackObservation]] = defaultdict(list)
        for observation in player_observations:
            if observation.id in player_by_observation_id:
                player_by_segment[observation.segment_id].append(observation)

        frames: list[PossessionFrame] = []
        last_clear: PossessionFrame | None = None
        for ball in ball_observations:
            nearby_players = [
                item
                for item in player_by_segment[ball.segment_id]
                if abs(item.timestamp_seconds - ball.timestamp_seconds) <= self._config.observation_alignment_seconds
            ]
            candidates = tuple(
                sorted(
                    (
                        self._possession_candidate(player_by_observation_id[player.id], player, ball)
                        for player in nearby_players
                    ),
                    key=lambda item: (-item.confidence.score, item.distance_pixels, item.player_track_id),
                )
            )
            frame = self._possession_frame(ball, candidates, last_clear)
            frames.append(frame)
            if frame.player_track_id is not None and not frame.confidence.ambiguous:
                last_clear = frame
        return tuple(frames)

    def _possession_candidate(
        self,
        player_track_id: str,
        player: TrackObservation,
        ball: TrackObservation,
    ) -> PossessionCandidate:
        distance = _distance_to_box(ball.centroid.x, ball.centroid.y, player.bounding_box)
        normalized = distance / max(player.bounding_box.width, player.bounding_box.height)
        score = _clamp(1 - normalized / self._config.possession_max_normalized_distance)
        if score >= self._config.possession_min_confidence:
            decision = AssociationDecision.ASSOCIATED
            reason = "Ball is geometrically close to the player observation."
        else:
            decision = AssociationDecision.UNASSOCIATED
            reason = "Ball is too far from the player observation."
        return PossessionCandidate(
            player_track_id,
            player.id,
            ball.id,
            ball.timestamp_seconds,
            distance,
            normalized,
            AssociationConfidence(score, decision, reason),
        )

    def _possession_frame(
        self,
        ball: TrackObservation,
        candidates: tuple[PossessionCandidate, ...],
        last_clear: PossessionFrame | None,
    ) -> PossessionFrame:
        viable = tuple(item for item in candidates if item.confidence.decision is AssociationDecision.ASSOCIATED)
        if not viable:
            if (
                last_clear is not None
                and ball.timestamp_seconds - last_clear.timestamp_seconds <= self._config.possession_gap_seconds
            ):
                return PossessionFrame(
                    ball.timestamp_seconds,
                    ball.id,
                    last_clear.player_track_id,
                    candidates,
                    AssociationConfidence(
                        _clamp(last_clear.confidence.score * 0.75),
                        AssociationDecision.ASSOCIATED,
                        "Possession carried across a short observation gap.",
                    ),
                    carried=True,
                )
            return PossessionFrame(
                ball.timestamp_seconds,
                ball.id,
                None,
                candidates,
                AssociationConfidence(0, AssociationDecision.UNASSOCIATED, "No player was close enough to the ball."),
            )

        top = viable[0]
        second = viable[1] if len(viable) > 1 else None
        if second is not None and top.confidence.score - second.confidence.score <= self._config.ambiguity_delta:
            return PossessionFrame(
                ball.timestamp_seconds,
                ball.id,
                None,
                candidates,
                AssociationConfidence(
                    top.confidence.score,
                    AssociationDecision.AMBIGUOUS,
                    "Multiple players are plausible possession candidates.",
                ),
            )
        return PossessionFrame(ball.timestamp_seconds, ball.id, top.player_track_id, candidates, top.confidence)

    def _shooter_attribution(
        self,
        event: ReleaseEvent,
        possession_frames: Sequence[PossessionFrame],
    ) -> ShooterAttribution:
        window_start = event.timestamp_seconds - self._config.release_window_seconds
        candidates = tuple(
            frame for frame in possession_frames if window_start <= frame.timestamp_seconds <= event.timestamp_seconds
        )
        if not candidates:
            return ShooterAttribution(
                event.id,
                None,
                AssociationConfidence(0, AssociationDecision.UNASSOCIATED, "No possession evidence before release."),
                (event.ball_observation_id,) if event.ball_observation_id is not None else (event.id,),
            )

        latest = candidates[-1]
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    latest.ball_observation_id,
                    *(
                        candidate.player_observation_id
                        for frame in candidates[-3:]
                        for candidate in frame.candidates
                        if latest.player_track_id is None or candidate.player_track_id == latest.player_track_id
                    ),
                )
            )
        )
        if latest.confidence.ambiguous:
            return ShooterAttribution(
                event.id,
                None,
                AssociationConfidence(
                    latest.confidence.score,
                    AssociationDecision.AMBIGUOUS,
                    "Possession at release is ambiguous.",
                ),
                evidence_ids,
            )
        if latest.player_track_id is None:
            return ShooterAttribution(event.id, None, latest.confidence, evidence_ids)
        return ShooterAttribution(event.id, latest.player_track_id, latest.confidence, evidence_ids)


def _observation_key(observation: TrackObservation) -> tuple[float, int, str, str]:
    return (observation.timestamp_seconds, observation.frame_index, observation.local_track_id, observation.id)


def _release_key(event: ReleaseEvent) -> tuple[float, int, str]:
    return (event.timestamp_seconds, event.frame_index, event.id)


def _distance_ratio(first: BoundingBox, second: BoundingBox) -> float:
    distance = math.hypot(first.centroid.x - second.centroid.x, first.centroid.y - second.centroid.y)
    scale = max(first.width, first.height, second.width, second.height)
    return distance / scale


def _distance_to_box(x: float, y: float, box: BoundingBox) -> float:
    dx = max(box.x - x, 0.0, x - (box.x + box.width))
    dy = max(box.y - y, 0.0, y - (box.y + box.height))
    return math.hypot(dx, dy)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
