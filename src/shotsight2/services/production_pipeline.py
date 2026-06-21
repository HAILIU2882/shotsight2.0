"""Concrete production runners for the local analysis worker."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from shotsight2.adapters.opencv import OpenCVFrameSource, OpenCVTrackingFrameSource
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.domain.camera_segments import CameraSegmentConfig
from shotsight2.domain.media import MediaMetadata, MediaProfileName, ProxyRequest, proxy_profile
from shotsight2.domain.persistence import (
    Artifact,
    BallTrack,
    JsonObject,
    ShotAttempt,
    ShotLocation,
    ShotOutcome,
    VideoStatus,
)
from shotsight2.domain.tracking import CameraSegmentInput, ModelConfig, TrackObservation
from shotsight2.ports.artifacts import ArtifactStore
from shotsight2.ports.media import MediaTool
from shotsight2.ports.repositories import (
    BallTrackRepository,
    CameraSegmentRepository,
    PlayerTrackRepository,
    VideoRepository,
)
from shotsight2.ports.tracking import (
    TrackingBackend,
    TrackingObservationRepository,
    TrackingPromptRepository,
)
from shotsight2.services.analysis_pipeline import PipelineContext, PipelineStageError
from shotsight2.services.artifact_rendering import (
    ArtifactRenderingService,
    RenderRunRequest,
)
from shotsight2.services.calibration import CalibrationService
from shotsight2.services.camera_segments import CameraSegmentService, to_persistence_segments
from shotsight2.services.outcome_classification import OutcomeClassificationService
from shotsight2.services.shot_lifecycle import ShotLifecycleService
from shotsight2.services.track_association import TrackAssociationService
from shotsight2.services.tracking import TrackingOrchestrator

TrackingBackendFactory = Callable[[str], TrackingBackend]


@dataclass(frozen=True, slots=True)
class _TrackingSegmentSummary:
    segment_id: str
    backend: str
    observations: int
    coverage: float
    identity_switches: int


class ValidationStage:
    """Resolve and probe the original artifact owned by the queued video."""

    def __init__(self, videos: VideoRepository, store: ArtifactStore, media: MediaTool) -> None:
        self._videos = videos
        self._store = store
        self._media = media

    def run(self, ctx: PipelineContext) -> PipelineContext:
        video = self._videos.get(ctx.video_id)
        if video is None or video.status is not VideoStatus.READY:
            raise PipelineStageError(f"Video {ctx.video_id} is not ready", "VIDEO_NOT_READY")
        source_id = ArtifactId(video.original_artifact_id)
        with self._store.local_path(source_id) as source:
            metadata = self._media.probe(source)
        return replace(
            ctx,
            source_artifact_id=str(source_id),
            video=video,
            media_metadata=metadata,
            frame_count=_frame_count(metadata.duration_seconds, metadata.video.average_fps, metadata.video.frame_count),
        )


class PreprocessingStage:
    """Create and register the run-specific normalized analysis proxy."""

    def __init__(self, store: ArtifactStore, media: MediaTool) -> None:
        self._store = store
        self._media = media

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if not ctx.source_artifact_id:
            raise PipelineStageError("Validation did not resolve source media", "SOURCE_NOT_RESOLVED")
        requested = ctx.configuration.get("proxy_profile", MediaProfileName.SPEED.value)
        if not isinstance(requested, str):
            raise PipelineStageError("proxy_profile must be a string", "INVALID_CONFIGURATION")
        try:
            profile = proxy_profile(requested)
        except ValueError as error:
            raise PipelineStageError(str(error), "INVALID_CONFIGURATION") from error

        temporary_id = self._store.create_temporary_file(ctx.video_id, ctx.run_id, suffix=".mp4")
        destination_id = self._store.proxy_id(ctx.video_id, ctx.run_id, f"analysis-{profile.name.value}.mp4")
        try:
            with (
                self._store.local_path(ArtifactId(ctx.source_artifact_id)) as source,
                self._store.local_path(temporary_id) as temporary,
            ):
                result = self._media.create_proxy(
                    ProxyRequest(source=source, destination=temporary, profile=profile, overwrite=True)
                )
            metadata = self._store.promote(temporary_id, destination_id)
        except Exception as error:
            _remove_temporary(self._store, temporary_id)
            raise PipelineStageError(str(error), "PREPROCESSING_FAILED") from error

        artifact = _artifact_record(
            ctx,
            metadata.artifact_id,
            "ANALYSIS_PROXY",
            metadata.logical_path,
            metadata.size_bytes,
        )
        return replace(
            ctx,
            analysis_artifact_id=str(destination_id),
            media_metadata=result.metadata,
            frame_count=_frame_count(
                result.metadata.duration_seconds,
                result.metadata.video.average_fps,
                result.metadata.video.frame_count,
            ),
            artifacts=(*ctx.artifacts, artifact),
        )


class CameraSegmentationStage:
    """Detect stable viewpoints and persist their calibration frames."""

    def __init__(
        self,
        store: ArtifactStore,
        media: MediaTool,
        segments: CameraSegmentRepository,
        *,
        config: CameraSegmentConfig | None = None,
    ) -> None:
        self._store = store
        self._media = media
        self._segments = segments
        self._config = config

    def run(self, ctx: PipelineContext) -> PipelineContext:
        source_id = _analysis_source(ctx)
        service = CameraSegmentService(self._media, OpenCVFrameSource(), config=self._config)
        with (
            self._store.local_path(source_id) as source,
            tempfile.TemporaryDirectory(prefix="shotsight-segments-") as directory,
        ):
            timeline = service.detect(source, ctx.run_id, Path(directory))
            records = list(to_persistence_segments(timeline))
            representative_ids: dict[str, str] = {}
            representative_artifacts: list[Artifact] = []
            for segment in timeline.stable_segments:
                artifact_id = self._store.render_id(ctx.video_id, ctx.run_id, f"calibration-{segment.id}.jpg")
                metadata = self._store.write_atomic(artifact_id, (segment.representative_frame.read_bytes(),))
                representative_ids[segment.id] = str(artifact_id)
                representative_artifacts.append(
                    _artifact_record(
                        ctx,
                        metadata.artifact_id,
                        "CALIBRATION_FRAME",
                        metadata.logical_path,
                        metadata.size_bytes,
                    )
                )

        persisted = tuple(
            replace(record, representative_artifact_id=representative_ids.get(record.id)) for record in records
        )
        self._segments.replace_for_run(ctx.run_id, persisted)
        return replace(
            ctx,
            segment_ids=tuple(item.id for item in persisted),
            segments=persisted,
            artifacts=(*ctx.artifacts, *representative_artifacts),
        )


class AutomaticCalibrationStage:
    """Persist conservative indicative calibration when no detector proposal exists."""

    def __init__(self, service: CalibrationService) -> None:
        self._service = service

    def run(self, ctx: PipelineContext) -> PipelineContext:
        calibrations = self._service.create_automatic_for_run(ctx.run_id, ctx.calibration_proposals)
        return replace(ctx, calibrations=calibrations)


class TrackingStage:
    """Track each stable segment against this job's analysis proxy."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        backend_factory: TrackingBackendFactory,
        observations: TrackingObservationRepository,
        prompts: TrackingPromptRepository,
        ball_tracks: BallTrackRepository,
    ) -> None:
        self._store = store
        self._backend_factory = backend_factory
        self._observations = observations
        self._prompts = prompts
        self._ball_tracks = ball_tracks

    def run(self, ctx: PipelineContext) -> PipelineContext:
        metadata = _require_metadata(ctx)
        source_id = _analysis_source(ctx)
        backend = self._backend_factory(ctx.backend_name)
        sampling_fps = _tracking_fps(ctx, metadata.video.average_fps)
        model_path = ctx.configuration.get("model_path")
        if model_path is not None and not isinstance(model_path, str):
            raise PipelineStageError("model_path must be a string", "INVALID_CONFIGURATION")
        observations: list[TrackObservation] = []
        summaries: list[_TrackingSegmentSummary] = []
        tracks: list[BallTrack] = []
        try:
            with self._store.local_path(source_id) as source:
                orchestrator = TrackingOrchestrator(
                    backend=backend,
                    frame_source=OpenCVTrackingFrameSource(source, sampling_fps=sampling_fps),
                    observations=self._observations,
                    prompts=self._prompts,
                    model_config=ModelConfig(
                        model_path=model_path,
                        device="mps" if ctx.backend_name == "mlx-sam3" else "cpu",
                    ),
                )
                for segment in ctx.segments:
                    if segment.stability_status.upper() != "STABLE":
                        continue
                    result = orchestrator.track_segment(
                        CameraSegmentInput(
                            id=segment.id,
                            analysis_run_id=ctx.run_id,
                            start_seconds=segment.start_seconds,
                            end_seconds=segment.end_seconds,
                            width=metadata.video.display_width,
                            height=metadata.video.display_height,
                            fps=metadata.video.average_fps,
                        )
                    )
                    observations.extend(result.observations)
                    summaries.append(
                        _TrackingSegmentSummary(
                            segment_id=segment.id,
                            backend=result.summary.backend_name,
                            observations=result.summary.observations,
                            coverage=result.summary.metrics.coverage,
                            identity_switches=result.summary.metrics.identity_switches,
                        )
                    )
        finally:
            backend.unload()

        track_artifact_id = self._store.track_id(ctx.video_id, ctx.run_id, "tracking-summary.json")
        payload = json.dumps(
            {
                "run_id": ctx.run_id,
                "segments": [
                    {
                        "segment_id": item.segment_id,
                        "backend": item.backend,
                        "observations": item.observations,
                        "coverage": item.coverage,
                        "identity_switches": item.identity_switches,
                    }
                    for item in summaries
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
        stored = self._store.write_atomic(track_artifact_id, (payload,))
        for summary in summaries:
            segment_id = summary.segment_id
            tracks.append(
                BallTrack(
                    id=str(uuid5(NAMESPACE_URL, f"shotsight:{ctx.run_id}:ball:{segment_id}")),
                    segment_id=segment_id,
                    observations_artifact_id=str(track_artifact_id),
                    backend_name=summary.backend,
                    coverage=summary.coverage,
                    identity_switches=summary.identity_switches,
                )
            )
        self._ball_tracks.replace_for_run(ctx.run_id, tracks)
        artifact = _artifact_record(ctx, stored.artifact_id, "TRACK_DATA", stored.logical_path, stored.size_bytes)
        return replace(ctx, observations=tuple(observations), artifacts=(*ctx.artifacts, artifact))


class ShotDetectionStage:
    """Associate players, detect released attempts, and classify outcomes."""

    def __init__(self, players: PlayerTrackRepository) -> None:
        self._players = players
        self._association = TrackAssociationService()
        self._lifecycle = ShotLifecycleService()
        self._outcomes = OutcomeClassificationService()

    def run(self, ctx: PipelineContext) -> PipelineContext:
        association = self._association.associate(
            analysis_run_id=ctx.run_id,
            video_id=ctx.video_id,
            segments=ctx.segments,
            observations=ctx.observations,
        )
        lifecycle = self._lifecycle.detect(
            analysis_run_id=ctx.run_id,
            segments=ctx.segments,
            observations=ctx.observations,
            possession_frames=association.possession_frames,
            calibrations=ctx.calibrations,
        )
        outcomes = self._outcomes.classify(
            candidates=lifecycle.candidates,
            observations=ctx.observations,
            calibrations=ctx.calibrations,
        )
        self._players.replace_for_run(ctx.run_id, association.players)
        return replace(
            ctx,
            players=association.players,
            player_links=association.observation_links,
            possession_frames=association.possession_frames,
            candidates=lifecycle.candidates,
            attempts=outcomes.attempts,
        )


class CourtMappingStage:
    """Create honest indicative release locations when metric calibration is absent."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        metadata = _require_metadata(ctx)
        observation_by_id = {item.id: item for item in ctx.observations}
        locations: list[ShotLocation] = []
        for attempt in ctx.attempts:
            observation = _release_player_observation(ctx, attempt, observation_by_id)
            if observation is None:
                continue
            locations.append(
                ShotLocation(
                    id=str(uuid5(NAMESPACE_URL, f"shotsight:{attempt.id}:indicative-location")),
                    shot_attempt_id=attempt.id,
                    court_x_m=None,
                    court_y_m=None,
                    normalized_x=_clamp(observation.centroid.x / metadata.video.display_width),
                    normalized_y=_clamp(observation.centroid.y / metadata.video.display_height),
                    region="INDICATIVE",
                    indicative=True,
                )
            )
        return replace(ctx, locations=tuple(locations))


class RenderingStage:
    """Generate the complete tracked video and review artifacts from real evidence."""

    def __init__(self, renderer: ArtifactRenderingService) -> None:
        self._renderer = renderer

    def run(self, ctx: PipelineContext) -> PipelineContext:
        metadata = _require_metadata(ctx)
        result = self._renderer.render_run(
            RenderRunRequest(
                video_id=ctx.video_id,
                run_id=ctx.run_id,
                source_artifact_id=_analysis_source(ctx),
                source_duration_seconds=metadata.duration_seconds,
                source_width=metadata.video.display_width,
                source_height=metadata.video.display_height,
                source_fps=metadata.video.average_fps,
                source_frame_count=metadata.video.frame_count,
                attempts=ctx.attempts,
                locations=ctx.locations,
                players=ctx.players,
            )
        )
        return replace(ctx, artifacts=(*ctx.artifacts, *result.artifacts))


class StatisticsStage:
    """Compute run-local aggregate counts before atomic publication."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        made = sum(item.automatic_outcome is ShotOutcome.MADE for item in ctx.attempts)
        missed = sum(item.automatic_outcome is ShotOutcome.MISSED for item in ctx.attempts)
        total = len(ctx.attempts)
        statistics: JsonObject = {
            "attempts": total,
            "made": made,
            "missed": missed,
            "uncertain": total - made - missed,
            "shooting_percentage": 0.0 if total == 0 else made / total,
        }
        return replace(ctx, statistics=statistics)


class FinalizationStage:
    """Reject incomplete output sets before the repository publishes the run."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.statistics is None:
            raise PipelineStageError("Statistics were not computed", "INCOMPLETE_PIPELINE")
        if not any(item.kind == "ANNOTATED_VIDEO" for item in ctx.artifacts):
            raise PipelineStageError("Annotated video was not rendered", "INCOMPLETE_PIPELINE")
        return ctx


def _analysis_source(ctx: PipelineContext) -> ArtifactId:
    if not ctx.analysis_artifact_id:
        raise PipelineStageError("Analysis proxy is unavailable", "PROXY_NOT_AVAILABLE")
    return ArtifactId(ctx.analysis_artifact_id)


def _require_metadata(ctx: PipelineContext) -> MediaMetadata:
    if ctx.media_metadata is None:
        raise PipelineStageError("Media metadata is unavailable", "MEDIA_NOT_PROBED")
    return ctx.media_metadata


def _frame_count(duration: float, fps: float, measured: int | None) -> int:
    return measured if measured is not None else max(1, round(duration * fps))


def _tracking_fps(ctx: PipelineContext, source_fps: float) -> float:
    value = ctx.configuration.get("tracking_fps", min(source_fps, 10.0))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PipelineStageError("tracking_fps must be a positive number", "INVALID_CONFIGURATION")
    return min(float(value), source_fps)


def _artifact_record(
    ctx: PipelineContext,
    artifact_id: ArtifactId,
    kind: str,
    logical_path: str,
    size_bytes: int,
) -> Artifact:
    return Artifact(
        id=str(artifact_id),
        video_id=ctx.video_id,
        analysis_run_id=ctx.run_id,
        kind=kind,
        logical_path=logical_path,
        version="production-pipeline-v1",
        size_bytes=size_bytes,
        created_at=datetime.now(UTC),
    )


def _release_player_observation(
    ctx: PipelineContext,
    attempt: ShotAttempt,
    observation_by_id: dict[str, TrackObservation],
) -> TrackObservation | None:
    if attempt.shooter_track_id is None:
        return None
    links = [item for item in ctx.player_links if item.player_track_id == attempt.shooter_track_id]
    if not links:
        return None
    nearest = min(links, key=lambda item: abs(item.timestamp_seconds - attempt.release_seconds))
    return observation_by_id.get(nearest.observation_id)


def _remove_temporary(store: ArtifactStore, artifact_id: ArtifactId) -> None:
    try:
        with store.local_path(artifact_id) as path:
            path.unlink(missing_ok=True)
    except Exception:
        return


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "AutomaticCalibrationStage",
    "CameraSegmentationStage",
    "CourtMappingStage",
    "FinalizationStage",
    "PreprocessingStage",
    "RenderingStage",
    "ShotDetectionStage",
    "StatisticsStage",
    "TrackingStage",
    "ValidationStage",
]
