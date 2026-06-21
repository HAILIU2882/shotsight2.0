"""Generate replay, annotated-video, shot-chart, and heatmap artifacts."""

from __future__ import annotations

import html
import math
import tempfile
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

import cv2

from shotsight2.domain import Artifact, PlayerTrack, ShotAttempt, ShotLocation, ShotOutcome
from shotsight2.domain.artifacts import ArtifactId, ArtifactMetadata
from shotsight2.domain.court import NormalizedCourtCoordinate, heatmap_bucket
from shotsight2.domain.media import (
    ClipRequest,
    RenderedFramesEncodeRequest,
)
from shotsight2.domain.persistence import JsonObject, JsonValue
from shotsight2.domain.rendering import (
    OverlayEvent,
    OverlayFrame,
    OverlayLabelKey,
    OverlayLocale,
    OverlayObject,
    OverlayState,
    OverlayTrajectory,
    RenderArtifactKind,
    RenderConfiguration,
    ReplayWindow,
    json_bytes,
    localized_label,
    outcome_label,
    overlay_state,
    replay_window,
)
from shotsight2.domain.tracking import TrackedObjectClass, TrackObservation, VisibilityState
from shotsight2.ports.artifacts import ArtifactStore, UnknownArtifactError
from shotsight2.ports.media import MediaTool
from shotsight2.ports.tracking import TrackingObservationRepository

_PNG_PATTERN = "frame-%06d.png"
_COURT_FILL = "#f8fafc"
_COURT_LINE = "#334155"
_MADE = "#15803d"
_MISSED = "#dc2626"
_UNCERTAIN = "#a16207"
_BALL = "#f97316"
_RIM = "#ef4444"
_PLAYER = "#2563eb"
_LOST = "#b91c1c"


class ArtifactRenderingError(RuntimeError):
    """Raised when artifact rendering cannot publish a complete output set."""


@dataclass(frozen=True, slots=True)
class RenderRunRequest:
    """All stored analysis records required to reproduce render outputs."""

    video_id: str
    run_id: str
    source_artifact_id: ArtifactId
    source_duration_seconds: float
    source_width: int
    source_height: int
    source_fps: float
    source_frame_count: int | None
    attempts: tuple[ShotAttempt, ...]
    locations: tuple[ShotLocation, ...]
    players: tuple[PlayerTrack, ...]
    config: RenderConfiguration = RenderConfiguration()


@dataclass(frozen=True, slots=True)
class RenderedArtifactMetadata:
    """Rich render metadata retained for diagnostics and metadata artifacts."""

    artifact_id: str
    kind: RenderArtifactKind
    logical_path: str
    size_bytes: int
    configuration_version: str
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None

    def to_json(self) -> JsonObject:
        """Serialize metadata without any physical filesystem path."""

        payload: JsonObject = {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "logical_path": self.logical_path,
            "size_bytes": self.size_bytes,
            "configuration_version": self.configuration_version,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
        }
        return payload


@dataclass(frozen=True, slots=True)
class RenderRunResult:
    """Published artifact records and rich metadata for one run."""

    artifacts: tuple[Artifact, ...]
    metadata: tuple[RenderedArtifactMetadata, ...]
    replay_windows: tuple[ReplayWindow, ...]


@dataclass(frozen=True, slots=True)
class _StagedRenderedArtifact:
    temporary_id: ArtifactId
    destination_id: ArtifactId
    kind: RenderArtifactKind
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class OverlaySequenceRequest:
    """Input for a physical frame-sequence renderer."""

    source: Path
    output_directory: Path
    frame_pattern: str
    width: int
    height: int
    duration_seconds: float
    frames_per_second: float
    source_frames_per_second: float
    source_frame_count: int | None
    observations: tuple[TrackObservation, ...]
    attempts: tuple[ShotAttempt, ...]
    players_by_id: Mapping[str, PlayerTrack]
    config: RenderConfiguration


class OverlayFrameSequenceRenderer(Protocol):
    """Render complete source frames with annotations to a numbered sequence."""

    def render_sequence(self, request: OverlaySequenceRequest) -> Path:
        """Return the image2-compatible frame pattern path."""


class OpenCVOverlayFrameSequenceRenderer:
    """Draw deterministic overlays onto sampled source frames using OpenCV."""

    def render_sequence(self, request: OverlaySequenceRequest) -> Path:
        """Write annotated PNG frames sampled at the configured output rate."""

        capture = cv2.VideoCapture(str(request.source))
        if not capture.isOpened():
            raise ArtifactRenderingError("Could not open source media for overlay rendering")
        if request.source_frames_per_second <= 0:
            capture.release()
            raise ArtifactRenderingError("Source frame rate must be positive")
        frame_count = _overlay_frame_count(request)
        observation_index = _ObservationTimelineIndex.build(request.observations)
        decoded_source_index = -1
        frame: Any | None = None
        try:
            for index in range(frame_count):
                timestamp = index / request.frames_per_second
                target_source_index = round(timestamp * request.source_frames_per_second)
                while decoded_source_index < target_source_index:
                    ok, decoded_frame = capture.read()
                    if not ok:
                        raise ArtifactRenderingError(
                            "Source decode ended before the complete overlay sequence "
                            f"({index}/{frame_count} frames written)"
                        )
                    frame = decoded_frame
                    decoded_source_index += 1
                if frame is None:
                    raise ArtifactRenderingError("Source decode produced no frames")
                overlay = _overlay_frame_from_index(
                    timestamp,
                    request.width,
                    request.height,
                    observation_index,
                    request.attempts,
                    request.players_by_id,
                    request.config,
                )
                _draw_cv2_overlay(frame, overlay)
                destination = request.output_directory / (request.frame_pattern % (index + 1))
                if not cv2.imwrite(str(destination), frame):
                    raise ArtifactRenderingError(f"Could not write overlay frame {destination.name}")
        finally:
            capture.release()
        return request.output_directory / request.frame_pattern


def _overlay_frame_count(request: OverlaySequenceRequest) -> int:
    """Return the sampled output count, preferring measured source frames."""

    if request.source_frame_count is None:
        return max(1, math.ceil(request.duration_seconds * request.frames_per_second - 1e-9))
    if request.source_frame_count <= 0:
        raise ArtifactRenderingError("Measured source frame count must be positive")
    sampled_count = math.ceil(
        request.source_frame_count * request.frames_per_second / request.source_frames_per_second - 1e-9
    )
    # Overlay rendering samples source frames; it never invents extra frames when
    # output and measured source rates differ only because of container timing.
    return max(1, min(request.source_frame_count, sampled_count))


class ArtifactRenderingService:
    """Render all derived review artifacts from stored analysis records."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        media_tool: MediaTool,
        observations: TrackingObservationRepository,
        frame_renderer: OverlayFrameSequenceRenderer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._media_tool = media_tool
        self._observations = observations
        self._frame_renderer = frame_renderer or OpenCVOverlayFrameSequenceRenderer()
        self._clock = clock or _utc_now

    def render_run(self, request: RenderRunRequest) -> RenderRunResult:
        """Generate all rendering artifacts or fail before metadata publication."""

        staged: list[_StagedRenderedArtifact] = []
        replay_windows: list[ReplayWindow] = []
        try:
            for attempt in request.attempts:
                lifecycle_start, lifecycle_end = _lifecycle_replay_bounds(attempt)
                window = replay_window(
                    attempt.id,
                    attempt.release_seconds,
                    request.source_duration_seconds,
                    request.config,
                    lifecycle_start_seconds=lifecycle_start,
                    lifecycle_end_seconds=lifecycle_end,
                )
                replay_windows.append(window)
                staged.append(self._stage_replay(request, attempt, window))

            staged.append(self._stage_annotated_video(request))
            staged.extend(self._stage_static_outputs(request))

            pre_metadata = tuple(self._predicted_metadata(request, item) for item in staged)
            staged.append(self._stage_metadata_artifact(request, pre_metadata))
        except Exception as error:
            for item in staged:
                _remove_temporary(self._artifact_store, item.temporary_id)
            message = "Rendering failed before a complete artifact set could be published"
            raise ArtifactRenderingError(message) from error

        try:
            _ensure_unique_destinations(staged)
            for item in staged:
                try:
                    self._artifact_store.metadata(item.destination_id)
                except UnknownArtifactError:
                    continue
                raise ArtifactRenderingError(f"Rendered artifact already exists: {item.destination_id}")
        except Exception:
            for item in staged:
                _remove_temporary(self._artifact_store, item.temporary_id)
            raise

        artifacts: list[Artifact] = []
        rich_metadata: list[RenderedArtifactMetadata] = []
        promoted: list[ArtifactId] = []
        try:
            for item in staged:
                metadata = self._artifact_store.promote(item.temporary_id, item.destination_id)
                promoted.append(item.destination_id)
                artifact, rich = self._artifact_record(
                    request,
                    item.kind,
                    metadata,
                    codec=item.codec,
                    width=item.width,
                    height=item.height,
                    duration_seconds=item.duration_seconds,
                )
                artifacts.append(artifact)
                rich_metadata.append(rich)
        except Exception as error:
            for item in staged:
                _remove_artifact(self._artifact_store, item.temporary_id)
            rollback_failures = [
                artifact_id
                for artifact_id in reversed(promoted)
                if not _remove_artifact(self._artifact_store, artifact_id)
            ]
            message = "Artifact promotion failed; all promoted outputs were rolled back"
            if rollback_failures:
                failed = ", ".join(str(item) for item in rollback_failures)
                message = f"Artifact promotion failed and rollback could not remove: {failed}"
            raise ArtifactRenderingError(message) from error
        return RenderRunResult(tuple(artifacts), tuple(rich_metadata), tuple(replay_windows))

    def _stage_replay(
        self,
        request: RenderRunRequest,
        attempt: ShotAttempt,
        window: ReplayWindow,
    ) -> _StagedRenderedArtifact:
        filename = f"replay-{_safe_token(attempt.id)}-{request.config.version_identifier}.mp4"
        destination_id = self._artifact_store.replay_id(request.video_id, request.run_id, filename)
        temporary_id = self._artifact_store.create_temporary_file(request.video_id, request.run_id, suffix=".mp4")
        try:
            with (
                self._artifact_store.local_path(request.source_artifact_id) as source,
                self._artifact_store.local_path(temporary_id) as temporary,
            ):
                self._media_tool.create_clip(
                    ClipRequest(
                        source=source,
                        destination=temporary,
                        start_seconds=window.start_seconds,
                        end_seconds=window.end_seconds,
                        overwrite=True,
                    )
                )
        except Exception:
            _remove_temporary(self._artifact_store, temporary_id)
            raise
        return _StagedRenderedArtifact(
            temporary_id=temporary_id,
            destination_id=destination_id,
            kind=RenderArtifactKind.REPLAY,
            codec=request.config.video_codec,
            width=request.source_width,
            height=request.source_height,
            duration_seconds=window.end_seconds - window.start_seconds,
        )

    def _stage_annotated_video(
        self,
        request: RenderRunRequest,
    ) -> _StagedRenderedArtifact:
        filename = f"annotated-{request.config.version_identifier}.mp4"
        destination_id = self._artifact_store.render_id(request.video_id, request.run_id, filename)
        temporary_id = self._artifact_store.create_temporary_file(request.video_id, request.run_id, suffix=".mp4")
        observations = tuple(self._observations.list_for_run(request.run_id))
        players_by_id = {player.id: player for player in request.players}
        try:
            with (
                self._artifact_store.local_path(request.source_artifact_id) as source,
                self._artifact_store.local_path(temporary_id) as temporary,
                tempfile.TemporaryDirectory(prefix="shotsight-render-") as directory,
            ):
                frame_directory = Path(directory)
                frame_pattern = self._frame_renderer.render_sequence(
                    OverlaySequenceRequest(
                        source=source,
                        output_directory=frame_directory,
                        frame_pattern=_PNG_PATTERN,
                        width=request.source_width,
                        height=request.source_height,
                        duration_seconds=request.source_duration_seconds,
                        frames_per_second=request.config.overlay_frames_per_second,
                        source_frames_per_second=request.source_fps,
                        source_frame_count=request.source_frame_count,
                        observations=observations,
                        attempts=request.attempts,
                        players_by_id=players_by_id,
                        config=request.config,
                    )
                )
                self._media_tool.encode_rendered_frames(
                    RenderedFramesEncodeRequest(
                        frame_pattern=frame_pattern,
                        destination=temporary,
                        frames_per_second=request.config.overlay_frames_per_second,
                        audio_source=source,
                        overwrite=True,
                    )
                )
        except Exception:
            _remove_temporary(self._artifact_store, temporary_id)
            raise
        return _StagedRenderedArtifact(
            temporary_id=temporary_id,
            destination_id=destination_id,
            kind=RenderArtifactKind.ANNOTATED_VIDEO,
            codec=request.config.video_codec,
            width=request.source_width,
            height=request.source_height,
            duration_seconds=request.source_duration_seconds,
        )

    def _stage_static_outputs(
        self,
        request: RenderRunRequest,
    ) -> tuple[_StagedRenderedArtifact, ...]:
        chart_data = shot_chart_data(request.attempts, request.locations, request.players, request.config)
        heatmap_data = heatmap_render_data(request.attempts, request.locations, request.config)
        outputs = (
            (
                RenderArtifactKind.SHOT_CHART_DATA,
                "shot-chart",
                ".json",
                json_bytes(chart_data),
            ),
            (
                RenderArtifactKind.SHOT_CHART_SVG,
                "shot-chart",
                ".svg",
                shot_chart_svg(chart_data, request.config).encode("utf-8"),
            ),
            (
                RenderArtifactKind.HEATMAP_DATA,
                "heatmap",
                ".json",
                json_bytes(heatmap_data),
            ),
            (
                RenderArtifactKind.HEATMAP_SVG,
                "heatmap",
                ".svg",
                heatmap_svg(heatmap_data, request.config).encode("utf-8"),
            ),
        )
        staged: list[_StagedRenderedArtifact] = []
        for kind, stem, suffix, payload in outputs:
            filename = f"{stem}-{request.config.version_identifier}{suffix}"
            destination_id = self._artifact_store.render_id(request.video_id, request.run_id, filename)
            temporary_id = self._artifact_store.create_temporary_file(request.video_id, request.run_id, suffix=suffix)
            try:
                self._artifact_store.write_atomic(temporary_id, (payload,))
            except Exception:
                _remove_temporary(self._artifact_store, temporary_id)
                raise
            staged.append(
                _StagedRenderedArtifact(
                    temporary_id=temporary_id,
                    destination_id=destination_id,
                    kind=kind,
                    width=request.config.chart_width,
                    height=request.config.chart_height,
                )
            )
        return tuple(staged)

    def _stage_metadata_artifact(
        self,
        request: RenderRunRequest,
        rich_metadata: Sequence[RenderedArtifactMetadata],
    ) -> _StagedRenderedArtifact:
        payload: JsonObject = {
            "video_id": request.video_id,
            "analysis_run_id": request.run_id,
            "configuration": request.config.to_json(),
            "configuration_version": request.config.version_identifier,
            "artifacts": [item.to_json() for item in rich_metadata],
        }
        filename = f"render-metadata-{request.config.version_identifier}.json"
        destination_id = self._artifact_store.render_id(request.video_id, request.run_id, filename)
        temporary_id = self._artifact_store.create_temporary_file(request.video_id, request.run_id, suffix=".json")
        try:
            self._artifact_store.write_atomic(temporary_id, (json_bytes(payload),))
        except Exception:
            _remove_temporary(self._artifact_store, temporary_id)
            raise
        return _StagedRenderedArtifact(
            temporary_id=temporary_id,
            destination_id=destination_id,
            kind=RenderArtifactKind.RENDER_METADATA,
        )

    def _predicted_metadata(
        self,
        request: RenderRunRequest,
        staged: _StagedRenderedArtifact,
    ) -> RenderedArtifactMetadata:
        temporary_metadata = self._artifact_store.metadata(staged.temporary_id)
        logical_path = str(staged.destination_id).partition(":")[2]
        return RenderedArtifactMetadata(
            artifact_id=str(staged.destination_id),
            kind=staged.kind,
            logical_path=logical_path,
            size_bytes=temporary_metadata.size_bytes,
            configuration_version=request.config.version_identifier,
            codec=staged.codec,
            width=staged.width,
            height=staged.height,
            duration_seconds=staged.duration_seconds,
        )

    def _artifact_record(
        self,
        request: RenderRunRequest,
        kind: RenderArtifactKind,
        metadata: ArtifactMetadata,
        *,
        codec: str | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_seconds: float | None = None,
    ) -> tuple[Artifact, RenderedArtifactMetadata]:
        rich = RenderedArtifactMetadata(
            artifact_id=str(metadata.artifact_id),
            kind=kind,
            logical_path=metadata.logical_path,
            size_bytes=metadata.size_bytes,
            configuration_version=request.config.version_identifier,
            codec=codec,
            width=width,
            height=height,
            duration_seconds=duration_seconds,
        )
        artifact = Artifact(
            id=_artifact_record_id(request.video_id, request.run_id, rich),
            video_id=request.video_id,
            analysis_run_id=request.run_id,
            kind=kind.value,
            logical_path=metadata.logical_path,
            version=request.config.version_identifier,
            size_bytes=metadata.size_bytes,
            created_at=self._clock(),
        )
        return artifact, rich


def overlay_frame_at(
    timestamp_seconds: float,
    width: int,
    height: int,
    observations: Sequence[TrackObservation],
    attempts: Sequence[ShotAttempt],
    players_by_id: Mapping[str, PlayerTrack],
    config: RenderConfiguration,
) -> OverlayFrame:
    """Build a deterministic overlay frame from observations near a timestamp."""

    return _overlay_frame_from_index(
        timestamp_seconds,
        width,
        height,
        _ObservationTimelineIndex.build(observations),
        attempts,
        players_by_id,
        config,
    )


@dataclass(frozen=True, slots=True)
class _ObservationTimelineIndex:
    """Timestamp index that avoids scanning every observation for every frame."""

    observations: tuple[TrackObservation, ...]
    timestamps: tuple[float, ...]
    ball_observations: tuple[TrackObservation, ...]
    ball_timestamps: tuple[float, ...]

    @classmethod
    def build(cls, observations: Sequence[TrackObservation]) -> _ObservationTimelineIndex:
        """Sort observations once and pre-index basketball trajectory samples."""

        ordered = tuple(sorted(observations, key=lambda item: (item.timestamp_seconds, *_observation_sort_key(item))))
        balls = tuple(item for item in ordered if item.object_class is TrackedObjectClass.BASKETBALL)
        return cls(
            observations=ordered,
            timestamps=tuple(item.timestamp_seconds for item in ordered),
            ball_observations=balls,
            ball_timestamps=tuple(item.timestamp_seconds for item in balls),
        )

    def nearby(self, timestamp_seconds: float, tolerance_seconds: float) -> tuple[TrackObservation, ...]:
        """Return observations inside one timestamp tolerance window."""

        start = bisect_left(self.timestamps, timestamp_seconds - tolerance_seconds)
        end = bisect_right(self.timestamps, timestamp_seconds + tolerance_seconds)
        return self.observations[start:end]

    def ball_between(self, start_seconds: float, end_seconds: float) -> tuple[TrackObservation, ...]:
        """Return trajectory basketball observations inside an inclusive range."""

        start = bisect_left(self.ball_timestamps, start_seconds)
        end = bisect_right(self.ball_timestamps, end_seconds)
        return self.ball_observations[start:end]


def _overlay_frame_from_index(
    timestamp_seconds: float,
    width: int,
    height: int,
    observation_index: _ObservationTimelineIndex,
    attempts: Sequence[ShotAttempt],
    players_by_id: Mapping[str, PlayerTrack],
    config: RenderConfiguration,
) -> OverlayFrame:
    """Build one overlay frame from a reusable observation index."""

    nearby = observation_index.nearby(timestamp_seconds, config.observation_tolerance_seconds)
    nearest_by_track: dict[tuple[TrackedObjectClass, str], TrackObservation] = {}
    for observation in nearby:
        key = (observation.object_class, observation.local_track_id)
        previous = nearest_by_track.get(key)
        if previous is None or abs(observation.timestamp_seconds - timestamp_seconds) < abs(
            previous.timestamp_seconds - timestamp_seconds
        ):
            nearest_by_track[key] = observation

    objects = tuple(
        _overlay_object(observation, players_by_id, config)
        for observation in sorted(nearest_by_track.values(), key=_observation_sort_key)
    )
    ball_points = tuple(
        observation.centroid
        for observation in observation_index.ball_between(
            timestamp_seconds - config.trajectory_seconds,
            timestamp_seconds,
        )
        if observation.visibility is not VisibilityState.LOST
    )
    trajectory = None if len(ball_points) < 2 else OverlayTrajectory(ball_points, OverlayState.CERTAIN)
    events = list(_attempt_events(timestamp_seconds, attempts, config))
    if not any(item.object_class is TrackedObjectClass.BASKETBALL for item in objects):
        events.append(
            OverlayEvent(
                timestamp_seconds=timestamp_seconds,
                label=localized_label(OverlayLabelKey.TRACKING_LOST, config.locale),
                state=OverlayState.TRACKING_LOST,
            )
        )
    return OverlayFrame(timestamp_seconds, width, height, objects, trajectory, tuple(events))


def overlay_frame_svg(frame: OverlayFrame, locale: OverlayLocale) -> str:
    """Render one overlay frame as deterministic SVG for regression tests."""

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{frame.width}" height="{frame.height}" '
        f'viewBox="0 0 {frame.width} {frame.height}">',
        '<rect width="100%" height="100%" fill="none"/>',
    ]
    if frame.trajectory is not None:
        points = " ".join(f"{_fmt(point.x)},{_fmt(point.y)}" for point in frame.trajectory.points)
        lines.append(f'<polyline points="{points}" fill="none" stroke="{_BALL}" stroke-width="2" opacity="0.65"/>')
    for item in frame.objects:
        lines.extend(_object_svg(item))
    for index, event in enumerate(frame.events):
        color = _state_color(event.state)
        y = 18 + index * 20
        lines.append(
            f'<text x="8" y="{y}" fill="{color}" font-size="14">'
            f"{html.escape(event.label)} {html.escape(localized_label(OverlayLabelKey.CONFIDENCE, locale))}</text>"
        )
    lines.append("</svg>")
    return "\n".join(lines)


def shot_chart_data(
    attempts: Sequence[ShotAttempt],
    locations: Sequence[ShotLocation],
    players: Sequence[PlayerTrack],
    config: RenderConfiguration,
) -> JsonObject:
    """Create deterministic shot-chart data with localized player labels."""

    by_attempt = {location.shot_attempt_id: location for location in locations}
    players_by_id = {player.id: player for player in players}
    points: list[JsonObject] = []
    missing: list[str] = []
    for attempt in sorted(attempts, key=lambda item: (item.release_seconds, item.id)):
        location = by_attempt.get(attempt.id)
        if location is None:
            missing.append(attempt.id)
            continue
        player = players_by_id.get(attempt.shooter_track_id or "")
        points.append(
            {
                "attempt_id": attempt.id,
                "release_seconds": attempt.release_seconds,
                "outcome": attempt.automatic_outcome.value,
                "outcome_label": outcome_label(attempt.automatic_outcome, config.locale),
                "shot_type": attempt.shot_type,
                "confidence": attempt.confidence,
                "shooter_track_id": attempt.shooter_track_id,
                "player_name": _player_name(attempt.shooter_track_id, players_by_id, config.locale),
                "normalized_x": location.normalized_x,
                "normalized_y": location.normalized_y,
                "court_x_m": location.court_x_m,
                "court_y_m": location.court_y_m,
                "region": location.region,
                "indicative": location.indicative,
                "label": player.display_name
                if player is not None
                else localized_label(OverlayLabelKey.PLAYER, config.locale),
            }
        )
    return cast(
        JsonObject,
        {
            "schema_version": config.schema_version,
            "configuration_version": config.version_identifier,
            "locale": config.locale.value,
            "width": config.chart_width,
            "height": config.chart_height,
            "points": points,
            "missing_location_attempt_ids": missing,
        },
    )


def heatmap_render_data(
    attempts: Sequence[ShotAttempt],
    locations: Sequence[ShotLocation],
    config: RenderConfiguration,
) -> JsonObject:
    """Create deterministic rectangular heatmap buckets."""

    attempts_by_id = {attempt.id: attempt for attempt in attempts}
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "made": 0, "missed": 0, "uncertain": 0})
    for location in locations:
        attempt = attempts_by_id.get(location.shot_attempt_id)
        if attempt is None:
            continue
        bucket = heatmap_bucket(
            NormalizedCourtCoordinate(location.normalized_x, location.normalized_y),
            columns=config.heatmap_columns,
            rows=config.heatmap_rows,
        )
        counts = buckets[bucket.key]
        counts["attempts"] += 1
        if attempt.automatic_outcome is ShotOutcome.MADE:
            counts["made"] += 1
        elif attempt.automatic_outcome is ShotOutcome.MISSED:
            counts["missed"] += 1
        else:
            counts["uncertain"] += 1
    cells: list[JsonObject] = []
    for key in sorted(buckets):
        column_text, row_text = key.split(":", maxsplit=1)
        counts = buckets[key]
        cells.append(
            {
                "key": key,
                "column": int(column_text),
                "row": int(row_text),
                "attempts": counts["attempts"],
                "made": counts["made"],
                "missed": counts["missed"],
                "uncertain": counts["uncertain"],
            }
        )
    return cast(
        JsonObject,
        {
            "schema_version": config.schema_version,
            "configuration_version": config.version_identifier,
            "locale": config.locale.value,
            "columns": config.heatmap_columns,
            "rows": config.heatmap_rows,
            "cells": cells,
        },
    )


def shot_chart_svg(data: Mapping[str, JsonValue], config: RenderConfiguration) -> str:
    """Render chart data as a deterministic half-court SVG."""

    width = config.chart_width
    height = config.chart_height
    lines = _court_svg_header(width, height)
    points = data["points"]
    if isinstance(points, list):
        for item in points:
            if not isinstance(item, dict):
                continue
            x = _json_float(item["normalized_x"]) * width
            y = _json_float(item["normalized_y"]) * height
            color = _outcome_color(str(item["outcome"]))
            label = html.escape(str(item["player_name"]))
            radius = 7 if bool(item["indicative"]) else 5
            lines.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{radius}" fill="{color}" opacity="0.9"/>')
            lines.append(f'<text x="{_fmt(x + 8)}" y="{_fmt(y + 4)}" font-size="11" fill="#0f172a">{label}</text>')
    lines.append("</svg>")
    return "\n".join(lines)


def heatmap_svg(data: Mapping[str, JsonValue], config: RenderConfiguration) -> str:
    """Render heatmap cells as a deterministic half-court SVG."""

    width = config.chart_width
    height = config.chart_height
    columns = config.heatmap_columns
    rows = config.heatmap_rows
    cell_width = width / columns
    cell_height = height / rows
    lines = _court_svg_header(width, height)
    cells = data["cells"]
    max_attempts = 1
    if isinstance(cells, list):
        max_attempts = max((_json_int(item["attempts"]) for item in cells if isinstance(item, dict)), default=1)
        for item in cells:
            if not isinstance(item, dict):
                continue
            attempts = _json_int(item["attempts"])
            opacity = 0.18 + 0.64 * attempts / max_attempts
            x = _json_int(item["column"]) * cell_width
            y = _json_int(item["row"]) * cell_height
            lines.append(
                f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(cell_width)}" '
                f'height="{_fmt(cell_height)}" fill="#f97316" opacity="{_fmt(opacity)}"/>'
            )
            lines.append(
                f'<text x="{_fmt(x + cell_width / 2)}" y="{_fmt(y + cell_height / 2)}" '
                f'text-anchor="middle" dominant-baseline="central" font-size="12" fill="#111827">{attempts}</text>'
            )
    lines.append("</svg>")
    return "\n".join(lines)


def _overlay_object(
    observation: TrackObservation,
    players_by_id: Mapping[str, PlayerTrack],
    config: RenderConfiguration,
) -> OverlayObject:
    label = _object_label(observation, players_by_id, config.locale)
    return OverlayObject(
        object_class=observation.object_class,
        track_id=observation.local_track_id,
        label=label,
        box=observation.bounding_box,
        centroid=observation.centroid,
        confidence=observation.confidence,
        state=overlay_state(
            observation.visibility,
            observation.confidence,
            low_confidence_threshold=config.low_confidence_threshold,
        ),
    )


def _object_label(
    observation: TrackObservation,
    players_by_id: Mapping[str, PlayerTrack],
    locale: OverlayLocale,
) -> str:
    if observation.object_class is TrackedObjectClass.PLAYER:
        player = players_by_id.get(observation.local_track_id)
        return player.display_name if player is not None else observation.local_track_id
    if observation.object_class is TrackedObjectClass.BASKETBALL:
        return localized_label(OverlayLabelKey.BALL, locale)
    return localized_label(OverlayLabelKey.RIM, locale)


def _attempt_events(
    timestamp_seconds: float,
    attempts: Sequence[ShotAttempt],
    config: RenderConfiguration,
) -> tuple[OverlayEvent, ...]:
    events: list[OverlayEvent] = []
    for attempt in attempts:
        if abs(attempt.release_seconds - timestamp_seconds) > config.observation_tolerance_seconds:
            continue
        label = (
            f"{localized_label(OverlayLabelKey.RELEASE, config.locale)}: "
            f"{outcome_label(attempt.automatic_outcome, config.locale)}"
        )
        state = OverlayState.UNCERTAIN if attempt.automatic_outcome is ShotOutcome.UNCERTAIN else OverlayState.CERTAIN
        events.append(OverlayEvent(attempt.release_seconds, label, state))
    return tuple(events)


def _draw_cv2_overlay(frame: Any, overlay: OverlayFrame) -> None:
    for item in overlay.objects:
        color = _cv2_color(item)
        top_left = (int(item.box.x), int(item.box.y))
        bottom_right = (int(item.box.x + item.box.width), int(item.box.y + item.box.height))
        cv2.rectangle(frame, top_left, bottom_right, color, 2)
        cv2.circle(frame, (int(item.centroid.x), int(item.centroid.y)), 4, color, -1)
        cv2.putText(
            frame,
            f"{item.label} {item.confidence:.2f}",
            (int(item.box.x), max(12, int(item.box.y) - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    if overlay.trajectory is not None:
        points = [(int(point.x), int(point.y)) for point in overlay.trajectory.points]
        for first, second in zip(points, points[1:], strict=False):
            cv2.line(frame, first, second, (22, 117, 245), 2)
    for index, event in enumerate(overlay.events):
        color = (28, 28, 185) if event.state is OverlayState.TRACKING_LOST else (255, 255, 255)
        cv2.putText(frame, event.label, (8, 24 + index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)


def _object_svg(item: OverlayObject) -> list[str]:
    color = _object_color(item)
    dash = ' stroke-dasharray="6 4"' if item.state in {OverlayState.UNCERTAIN, OverlayState.OCCLUDED} else ""
    opacity = "0.55" if item.state is OverlayState.OCCLUDED else "0.95"
    label = html.escape(f"{item.label} {item.confidence:.2f}")
    return [
        f'<rect x="{_fmt(item.box.x)}" y="{_fmt(item.box.y)}" width="{_fmt(item.box.width)}" '
        f'height="{_fmt(item.box.height)}" fill="none" stroke="{color}" stroke-width="2"{dash} opacity="{opacity}"/>',
        f'<circle cx="{_fmt(item.centroid.x)}" cy="{_fmt(item.centroid.y)}" r="4" fill="{color}" opacity="{opacity}"/>',
        f'<text x="{_fmt(item.box.x)}" y="{_fmt(max(12, item.box.y - 4))}" fill="{color}" '
        f'font-size="12">{label}</text>',
    ]


def _court_svg_header(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{_COURT_FILL}"/>',
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" fill="none" '
        f'stroke="{_COURT_LINE}" stroke-width="2"/>',
        f'<line x1="0" y1="{_fmt(height / 2)}" x2="{width}" y2="{_fmt(height / 2)}" '
        f'stroke="{_COURT_LINE}" opacity="0.25"/>',
        f'<circle cx="{_fmt(width * 0.085)}" cy="{_fmt(height / 2)}" r="{_fmt(width * 0.055)}" fill="none" '
        f'stroke="{_RIM}" stroke-width="2"/>',
        f'<path d="M {_fmt(width * 0.08)} {_fmt(height * 0.06)} C {_fmt(width * 0.72)} {_fmt(height * 0.18)}, '
        f'{_fmt(width * 0.72)} {_fmt(height * 0.82)}, {_fmt(width * 0.08)} {_fmt(height * 0.94)}" '
        f'fill="none" stroke="{_COURT_LINE}" stroke-width="2" opacity="0.55"/>',
    ]


def _artifact_record_id(video_id: str, run_id: str, metadata: RenderedArtifactMetadata) -> str:
    return str(uuid5(NAMESPACE_URL, f"shotsight:{video_id}:{run_id}:{metadata.kind}:{metadata.logical_path}"))


def _ensure_unique_destinations(staged: Sequence[_StagedRenderedArtifact]) -> None:
    seen: set[ArtifactId] = set()
    for item in staged:
        if item.destination_id in seen:
            raise ArtifactRenderingError(f"Duplicate rendered destination: {item.destination_id}")
        seen.add(item.destination_id)


def _remove_temporary(store: ArtifactStore, temporary_id: ArtifactId) -> None:
    _remove_artifact(store, temporary_id)


def _remove_artifact(store: ArtifactStore, artifact_id: ArtifactId) -> bool:
    """Best-effort removal used to compensate failed multi-artifact promotion."""

    try:
        with store.local_path(artifact_id) as path:
            path.unlink(missing_ok=True)
    except UnknownArtifactError:
        return True
    except Exception:
        return False
    return True


def _lifecycle_replay_bounds(attempt: ShotAttempt) -> tuple[float | None, float | None]:
    """Extract trustworthy lifecycle start/result bounds from persisted evidence."""

    if attempt.evidence.get("source") != "shot_lifecycle":
        return None, None

    start_candidates: list[float] = []
    end_candidates: list[float] = []
    events = attempt.evidence.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            timestamp = _optional_json_float(event.get("timestamp_seconds"))
            kind = event.get("kind")
            if timestamp is None:
                continue
            if kind == "possession_entered" and timestamp <= attempt.release_seconds:
                start_candidates.append(timestamp)
            elif timestamp >= attempt.release_seconds:
                end_candidates.append(timestamp)

    evidence = attempt.evidence.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict) or item.get("kind") != "possession":
                continue
            timestamp = _optional_json_float(item.get("timestamp_seconds"))
            if timestamp is not None and timestamp <= attempt.release_seconds:
                start_candidates.append(timestamp)

    result_window = attempt.evidence.get("result_window")
    if isinstance(result_window, dict):
        result_end = _optional_json_float(result_window.get("end_seconds"))
        if result_end is not None and result_end >= attempt.release_seconds:
            end_candidates.append(result_end)

    start = min(start_candidates) if start_candidates else None
    end = max(end_candidates) if end_candidates else None
    return start, end


def _player_name(
    player_track_id: str | None,
    players_by_id: Mapping[str, PlayerTrack],
    locale: OverlayLocale,
) -> str:
    if player_track_id is None:
        return localized_label(OverlayLabelKey.PLAYER, locale)
    player = players_by_id.get(player_track_id)
    return player.display_name if player is not None else player_track_id


def _observation_sort_key(observation: TrackObservation) -> tuple[str, str]:
    return (observation.object_class.value, observation.local_track_id)


def _object_color(item: OverlayObject) -> str:
    if item.state is OverlayState.TRACKING_LOST:
        return _LOST
    if item.object_class is TrackedObjectClass.BASKETBALL:
        return _BALL
    if item.object_class is TrackedObjectClass.RIM:
        return _RIM
    return _PLAYER


def _state_color(state: OverlayState) -> str:
    if state is OverlayState.TRACKING_LOST:
        return _LOST
    if state is OverlayState.OCCLUDED:
        return "#7c3aed"
    if state is OverlayState.UNCERTAIN:
        return _UNCERTAIN
    return "#f8fafc"


def _cv2_color(item: OverlayObject) -> tuple[int, int, int]:
    if item.state is OverlayState.TRACKING_LOST:
        return (28, 28, 185)
    if item.object_class is TrackedObjectClass.BASKETBALL:
        return (22, 117, 245)
    if item.object_class is TrackedObjectClass.RIM:
        return (68, 68, 239)
    return (235, 99, 37)


def _outcome_color(outcome: str) -> str:
    if outcome == ShotOutcome.MADE.value:
        return _MADE
    if outcome == ShotOutcome.MISSED.value:
        return _MISSED
    return _UNCERTAIN


def _safe_token(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)


def _json_float(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected numeric JSON value")
    return float(value)


def _optional_json_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _json_int(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected integer JSON value")
    return value


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _utc_now() -> datetime:
    return datetime.now(UTC)
