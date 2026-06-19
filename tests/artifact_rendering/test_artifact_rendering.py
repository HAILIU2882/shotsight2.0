"""Artifact rendering service and deterministic overlay tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from shotsight2.adapters.filesystem.artifact_store import ArtifactStoreRoots, FileSystemArtifactStore
from shotsight2.domain import PlayerTrack, ReviewStatus, ShotAttempt, ShotLocation, ShotOutcome
from shotsight2.domain.artifacts import ArtifactId
from shotsight2.domain.media import (
    AudioStreamMetadata,
    ClipRequest,
    ClipResult,
    CommandRecord,
    EncodeResult,
    FrameExtractionRequest,
    FrameExtractionResult,
    MediaMetadata,
    MediaToolStatus,
    OverlayEncodeRequest,
    ProxyRequest,
    ProxyResult,
    RenderedFramesEncodeRequest,
    ToolStatus,
    VideoStreamMetadata,
)
from shotsight2.domain.persistence import JsonObject
from shotsight2.domain.rendering import (
    OverlayLabelKey,
    OverlayLocale,
    RenderArtifactKind,
    RenderConfiguration,
    localized_label,
    replay_window,
)
from shotsight2.domain.tracking import (
    BoundingBox,
    ImagePoint,
    ObservationProvenance,
    TrackedObjectClass,
    TrackObservation,
    VisibilityState,
)
from shotsight2.services.artifact_rendering import (
    ArtifactRenderingError,
    ArtifactRenderingService,
    OverlaySequenceRequest,
    RenderRunRequest,
    heatmap_render_data,
    heatmap_svg,
    overlay_frame_at,
    overlay_frame_svg,
    shot_chart_data,
    shot_chart_svg,
)

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


def test_render_run_stages_outputs_promotes_complete_artifact_set(tmp_path: Path) -> None:
    roots = ArtifactStoreRoots.under(tmp_path / "data")
    store = FileSystemArtifactStore(roots)
    source = _source_artifact(store)
    media = _FakeMediaTool()
    renderer = _FakeFrameRenderer()
    request = _request(source)
    service = ArtifactRenderingService(
        artifact_store=store,
        media_tool=media,
        observations=_ObservationRepository((_observation("ball", TrackedObjectClass.BASKETBALL, 0.2),)),
        frame_renderer=renderer,
        clock=lambda: NOW,
    )

    result = service.render_run(request)

    assert {artifact.kind for artifact in result.artifacts} == {
        RenderArtifactKind.REPLAY.value,
        RenderArtifactKind.ANNOTATED_VIDEO.value,
        RenderArtifactKind.SHOT_CHART_DATA.value,
        RenderArtifactKind.SHOT_CHART_SVG.value,
        RenderArtifactKind.HEATMAP_DATA.value,
        RenderArtifactKind.HEATMAP_SVG.value,
        RenderArtifactKind.RENDER_METADATA.value,
    }
    assert media.clip_requests[0].start_seconds == 0.0
    assert media.clip_requests[0].end_seconds == 1.0
    assert media.encode_requests[0].frames_per_second == request.config.overlay_frames_per_second
    assert renderer.requests[0].players_by_id["player-1"].display_name == "Alice"
    assert all(not metadata.logical_path.startswith("/") for metadata in result.metadata)
    assert all("/Users/" not in metadata.logical_path for metadata in result.metadata)
    assert len(store.inventory_for_video(request.video_id).artifacts) == 8


def test_encode_failure_cleans_temporary_outputs_and_publishes_nothing(tmp_path: Path) -> None:
    roots = ArtifactStoreRoots.under(tmp_path / "data")
    store = FileSystemArtifactStore(roots)
    source = _source_artifact(store)
    service = ArtifactRenderingService(
        artifact_store=store,
        media_tool=_FakeMediaTool(fail_encode=True),
        observations=_ObservationRepository(()),
        frame_renderer=_FakeFrameRenderer(),
        clock=lambda: NOW,
    )

    with pytest.raises(ArtifactRenderingError):
        service.render_run(_request(source))

    assert [item.artifact_id for item in store.inventory_for_video("video-1").artifacts] == [source]
    assert [path for path in roots.temporary.rglob("*") if path.is_file()] == []


def test_duplicate_replay_destinations_fail_before_publishing(tmp_path: Path) -> None:
    roots = ArtifactStoreRoots.under(tmp_path / "data")
    store = FileSystemArtifactStore(roots)
    source = _source_artifact(store)
    media = _FakeMediaTool()
    request = _request(
        source,
        attempts=(
            _attempt("attempt/a", release_seconds=0.2),
            _attempt("attempt:a", release_seconds=0.4),
        ),
        locations=(),
    )
    service = ArtifactRenderingService(
        artifact_store=store,
        media_tool=media,
        observations=_ObservationRepository(()),
        frame_renderer=_FakeFrameRenderer(),
        clock=lambda: NOW,
    )

    with pytest.raises(ArtifactRenderingError, match="Duplicate rendered destination"):
        service.render_run(request)

    assert len(media.clip_requests) == 2
    assert [item.artifact_id for item in store.inventory_for_video("video-1").artifacts] == [source]
    assert [path for path in roots.temporary.rglob("*") if path.is_file()] == []


def test_overlay_localization_current_names_and_tracking_states() -> None:
    config = RenderConfiguration(locale=OverlayLocale.CHINESE, observation_tolerance_seconds=0.05)
    players = {"player-1": PlayerTrack("player-1", "run-1", "video-1", "Player 1", "Alice", 0.9)}
    observations = (
        _observation(
            "player-observation",
            TrackedObjectClass.PLAYER,
            1.0,
            track_id="player-1",
            visibility=VisibilityState.OCCLUDED,
        ),
        _observation(
            "rim-observation",
            TrackedObjectClass.RIM,
            1.0,
            track_id="rim-1",
            visibility=VisibilityState.PARTIAL,
            confidence=0.4,
        ),
    )

    frame = overlay_frame_at(1.0, 120, 80, observations, (_attempt(release_seconds=1.0),), players, config)
    svg = overlay_frame_svg(frame, config.locale)

    assert "Alice 0.91" in svg
    assert localized_label(OverlayLabelKey.TRACKING_LOST, OverlayLocale.CHINESE) in svg
    assert localized_label(OverlayLabelKey.RELEASE, OverlayLocale.CHINESE) in svg
    assert 'stroke-dasharray="6 4"' in svg


def test_overlay_frame_svg_visual_regression_fixture() -> None:
    config = RenderConfiguration(observation_tolerance_seconds=0.05)
    players = {"player-1": PlayerTrack("player-1", "run-1", "video-1", "Player 1", "Alice", 0.9)}
    observations = (
        _observation("ball-1", TrackedObjectClass.BASKETBALL, 2.0, box=BoundingBox(10, 12, 8, 8)),
        _observation("rim-1", TrackedObjectClass.RIM, 2.0, track_id="rim-1", box=BoundingBox(70, 14, 20, 10)),
        _observation(
            "player-1-observation",
            TrackedObjectClass.PLAYER,
            2.0,
            track_id="player-1",
            box=BoundingBox(30, 25, 16, 34),
        ),
    )

    svg = overlay_frame_svg(
        overlay_frame_at(2.0, 100, 80, observations, (_attempt(release_seconds=2.0),), players, config),
        config.locale,
    )

    assert svg == "\n".join(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">',
            '<rect width="100%" height="100%" fill="none"/>',
            '<rect x="10" y="12" width="8" height="8" fill="none" stroke="#f97316" stroke-width="2" opacity="0.95"/>',
            '<circle cx="14" cy="16" r="4" fill="#f97316" opacity="0.95"/>',
            '<text x="10" y="12" fill="#f97316" font-size="12">Ball 0.91</text>',
            '<rect x="30" y="25" width="16" height="34" fill="none" stroke="#2563eb" stroke-width="2" opacity="0.95"/>',
            '<circle cx="38" cy="42" r="4" fill="#2563eb" opacity="0.95"/>',
            '<text x="30" y="21" fill="#2563eb" font-size="12">Alice 0.91</text>',
            '<rect x="70" y="14" width="20" height="10" fill="none" stroke="#ef4444" stroke-width="2" opacity="0.95"/>',
            '<circle cx="80" cy="19" r="4" fill="#ef4444" opacity="0.95"/>',
            '<text x="70" y="12" fill="#ef4444" font-size="12">Rim 0.91</text>',
            '<text x="8" y="18" fill="#f8fafc" font-size="14">Release: Made Confidence</text>',
            "</svg>",
        )
    )


def test_shot_chart_and_heatmap_outputs_are_deterministic_and_localized() -> None:
    config = RenderConfiguration(locale=OverlayLocale.CHINESE, chart_width=100, chart_height=80)
    attempts = (_attempt(), _attempt(attempt_id="attempt-missing", release_seconds=0.8))
    locations = (_location(),)
    players = (PlayerTrack("player-1", "run-1", "video-1", "Player 1", "Alice", 0.9),)

    chart = shot_chart_data(attempts, locations, players, config)
    heatmap = heatmap_render_data(attempts, locations, config)
    chart_points = cast(list[JsonObject], chart["points"])
    heatmap_cells = cast(list[JsonObject], heatmap["cells"])

    assert chart["missing_location_attempt_ids"] == ["attempt-missing"]
    assert chart_points[0]["player_name"] == "Alice"
    assert chart_points[0]["outcome_label"] == "命中"
    assert heatmap_cells[0]["attempts"] == 1
    assert "Alice" in shot_chart_svg(chart, config)
    assert '<rect x="50" y="32"' in heatmap_svg(heatmap, config)


def test_render_configuration_versions_and_replay_windows_are_stable() -> None:
    english = RenderConfiguration(locale=OverlayLocale.ENGLISH)
    chinese = RenderConfiguration(locale=OverlayLocale.CHINESE)
    first = replay_window("attempt-1", 0.5, 1.0, english)
    second = replay_window("attempt-1", 0.5, 1.0, english)

    assert first == second
    assert first.start_seconds == 0.0
    assert first.end_seconds == 1.0
    assert english.version_identifier == RenderConfiguration(locale=OverlayLocale.ENGLISH).version_identifier
    assert english.version_identifier != chinese.version_identifier


@dataclass(slots=True)
class _FakeMediaTool:
    fail_encode: bool = False
    clip_requests: list[ClipRequest] = field(default_factory=list)
    encode_requests: list[RenderedFramesEncodeRequest] = field(default_factory=list)

    def status(self) -> MediaToolStatus:
        tool = ToolStatus("ffmpeg", True, Path("/fake/ffmpeg"), "fake")
        return MediaToolStatus(tool, tool)

    def probe(self, source: Path) -> MediaMetadata:
        return _metadata(source)

    def create_proxy(self, request: ProxyRequest) -> ProxyResult:
        raise NotImplementedError

    def extract_frame(self, request: FrameExtractionRequest) -> FrameExtractionResult:
        raise NotImplementedError

    def create_clip(self, request: ClipRequest) -> ClipResult:
        self.clip_requests.append(request)
        request.destination.write_bytes(b"replay-video")
        return ClipResult(
            request.destination,
            request.start_seconds,
            request.end_seconds,
            request.start_seconds,
            request.end_seconds,
            _metadata(request.destination),
            CommandRecord("fake-ffmpeg", (str(request.destination),)),
        )

    def encode_rendered_frames(self, request: RenderedFramesEncodeRequest) -> EncodeResult:
        self.encode_requests.append(request)
        request.destination.write_bytes(b"partial-video" if self.fail_encode else b"annotated-video")
        if self.fail_encode:
            raise RuntimeError("encode failed")
        return EncodeResult(request.destination, _metadata(request.destination), CommandRecord("fake-ffmpeg", ()))

    def encode_overlay(self, request: OverlayEncodeRequest) -> EncodeResult:
        raise NotImplementedError


class _FakeFrameRenderer:
    def __init__(self) -> None:
        self.requests: list[OverlaySequenceRequest] = []

    def render_sequence(self, request: OverlaySequenceRequest) -> Path:
        self.requests.append(request)
        (request.output_directory / "frame-000001.png").write_bytes(b"png")
        return request.output_directory / request.frame_pattern


class _ObservationRepository:
    def __init__(self, observations: Sequence[TrackObservation]) -> None:
        self._observations = tuple(observations)

    def replace_for_segment(self, segment_id: str, observations: Sequence[TrackObservation]) -> None:
        raise AssertionError("rendering must not mutate tracking observations")

    def list_for_segment(self, segment_id: str) -> list[TrackObservation]:
        return [item for item in self._observations if item.segment_id == segment_id]

    def list_for_run(self, run_id: str) -> list[TrackObservation]:
        return list(self._observations)


def _source_artifact(store: FileSystemArtifactStore) -> ArtifactId:
    source = store.original_id("video-1", "mp4")
    store.write_atomic(source, (b"source-video",))
    return source


def _request(
    source: ArtifactId,
    *,
    attempts: tuple[ShotAttempt, ...] | None = None,
    locations: tuple[ShotLocation, ...] | None = None,
) -> RenderRunRequest:
    return RenderRunRequest(
        video_id="video-1",
        run_id="run-1",
        source_artifact_id=source,
        source_duration_seconds=1.0,
        source_width=160,
        source_height=90,
        source_fps=10.0,
        attempts=attempts or (_attempt(release_seconds=0.2),),
        locations=locations if locations is not None else (_location(),),
        players=(PlayerTrack("player-1", "run-1", "video-1", "Player 1", "Alice", 0.9),),
        config=RenderConfiguration(replay_lead_seconds=0.5, replay_trail_seconds=1.0),
    )


def _attempt(attempt_id: str = "attempt-1", *, release_seconds: float = 0.2) -> ShotAttempt:
    return ShotAttempt(
        attempt_id,
        "run-1",
        "player-1",
        release_seconds,
        ShotOutcome.MADE,
        "THREE_POINT",
        0.82,
        ReviewStatus.UNREVIEWED,
        {"source": "test"},
    )


def _location(attempt_id: str = "attempt-1") -> ShotLocation:
    return ShotLocation(
        f"location-{attempt_id}",
        attempt_id,
        7.0,
        1.0,
        0.5,
        0.4,
        "RIGHT_WING_THREE",
        False,
    )


def _observation(
    observation_id: str,
    object_class: TrackedObjectClass,
    timestamp: float,
    *,
    track_id: str = "ball-1",
    box: BoundingBox | None = None,
    visibility: VisibilityState = VisibilityState.VISIBLE,
    confidence: float = 0.91,
) -> TrackObservation:
    bounding_box = box or BoundingBox(10, 10, 10, 10)
    return TrackObservation(
        observation_id,
        "segment-1",
        int(timestamp * 10),
        timestamp,
        object_class,
        track_id,
        bounding_box,
        ImagePoint(bounding_box.x + bounding_box.width / 2, bounding_box.y + bounding_box.height / 2),
        confidence,
        visibility,
        visibility is VisibilityState.OCCLUDED,
        ObservationProvenance("opencv-cpu", "4.13", "heuristic", "session-1"),
    )


def _metadata(path: Path) -> MediaMetadata:
    return MediaMetadata(
        path=path,
        format_name="mp4",
        duration_seconds=1.0,
        size_bytes=path.stat().st_size if path.exists() else 1,
        bit_rate_bps=None,
        video=VideoStreamMetadata(
            stream_index=0,
            codec="h264",
            width=160,
            height=90,
            display_width=160,
            display_height=90,
            average_fps=10.0,
            nominal_fps=10.0,
            pixel_format="yuv420p",
            rotation_degrees=0,
            frame_count=10,
            is_variable_frame_rate=False,
        ),
        audio_streams=(AudioStreamMetadata(1, "aac", 44_100, 1),),
    )
