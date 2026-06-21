"""Video-scoped context for the intentionally disabled repair workflow."""

from __future__ import annotations

from dataclasses import dataclass

from shotsight2.domain import AnalysisRun, CameraSegment, RunStatus
from shotsight2.ports.repositories import AnalysisRunRepository, CameraSegmentRepository, VideoRepository


class TrackingRepairNotFoundError(LookupError):
    """Raised when a video, run, or segment is outside the requested video."""


class TrackingRepairUnavailableError(RuntimeError):
    """Raised because completed-run repair cannot yet be applied safely."""


@dataclass(frozen=True, slots=True)
class TrackingRepairSegment:
    """One stable segment belonging to the selected video's run."""

    segment_id: str
    start_seconds: float
    end_seconds: float
    representative_artifact_id: str | None


@dataclass(frozen=True, slots=True)
class TrackingRepairContext:
    """Truthful repair availability for one video and analysis run."""

    video_id: str
    run_id: str | None
    segments: tuple[TrackingRepairSegment, ...]
    supported: bool = False


class TrackingRepairService:
    """Resolve repair targets without binding a process-global media source."""

    def __init__(
        self,
        videos: VideoRepository,
        runs: AnalysisRunRepository,
        segments: CameraSegmentRepository,
    ) -> None:
        self._videos = videos
        self._runs = runs
        self._segments = segments

    def context(self, video_id: str, run_id: str | None = None) -> TrackingRepairContext:
        """Return only stable segments owned by the requested video."""

        if self._videos.get(video_id) is None:
            raise TrackingRepairNotFoundError(f"Video {video_id!r} was not found")
        run = self._select_run(video_id, run_id)
        if run is None:
            return TrackingRepairContext(video_id=video_id, run_id=None, segments=())
        segments = tuple(
            self._to_segment(item)
            for item in self._segments.list_for_run(run.id)
            if item.stability_status.upper() == "STABLE"
        )
        return TrackingRepairContext(video_id=video_id, run_id=run.id, segments=segments)

    def reject_submission(self, video_id: str, segment_id: str) -> None:
        """Validate target ownership, then reject the unsupported mutation."""

        segment = self._segments.get(segment_id)
        if segment is None:
            raise TrackingRepairNotFoundError(f"Segment {segment_id!r} was not found")
        run = self._runs.get(segment.analysis_run_id)
        if run is None or run.video_id != video_id:
            raise TrackingRepairNotFoundError(f"Segment {segment_id!r} does not belong to video {video_id!r}")
        raise TrackingRepairUnavailableError(
            "Tracking repair is not yet supported because prompts cannot be applied atomically "
            "to a completed run or transferred safely to a new camera segmentation."
        )

    def _select_run(self, video_id: str, run_id: str | None) -> AnalysisRun | None:
        runs = self._runs.list_for_video(video_id)
        if run_id:
            selected = next((run for run in runs if run.id == run_id), None)
            if selected is None:
                raise TrackingRepairNotFoundError(f"Analysis run {run_id!r} does not belong to video {video_id!r}")
            return selected
        candidates = [run for run in runs if run.status is RunStatus.COMPLETED]
        if not candidates:
            return None
        return max(candidates, key=lambda run: (run.published, run.started_at, run.id))

    @staticmethod
    def _to_segment(segment: CameraSegment) -> TrackingRepairSegment:
        return TrackingRepairSegment(
            segment_id=segment.id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            representative_artifact_id=segment.representative_artifact_id,
        )
