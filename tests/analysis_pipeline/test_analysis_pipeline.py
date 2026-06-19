"""Pipeline orchestrator tests: success, failure at every stage, cleanup, and republish."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.persistence import (
    AnalysisRun,
    AnalysisStage,
    Artifact,
    JsonObject,
    RunStatus,
    ShotAttempt,
    ShotLocation,
)
from shotsight2.services.analysis_jobs import AnalysisFailure
from shotsight2.services.analysis_pipeline import (
    AnalysisPipelineOrchestrator,
    PipelineContext,
    PipelineStageError,
    PipelineStageRunner,
    StageResult,
    StageSpec,
)

# ---------------------------------------------------------------------------
# Fixed clock
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_T1 = datetime(2024, 1, 1, 0, 0, 5, tzinfo=UTC)


def _clock_sequence(*times: datetime) -> list[datetime]:
    return list(times)


class _StepClock:
    """Return successive datetimes from a fixed list; repeat last when exhausted."""

    def __init__(self, steps: list[datetime]) -> None:
        self._steps = steps
        self._idx = 0

    def __call__(self) -> datetime:
        v = self._steps[self._idx]
        if self._idx < len(self._steps) - 1:
            self._idx += 1
        return v


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeJobService:
    def __init__(self) -> None:
        self.progress_calls: list[tuple[str, AnalysisStage, float]] = []
        self.completed_calls: list[str] = []
        self.failed_calls: list[tuple[str, AnalysisFailure]] = []

    def update_progress(self, job_id: str, stage: AnalysisStage, progress: float) -> None:
        self.progress_calls.append((job_id, stage, progress))

    def mark_completed(self, job_id: str) -> None:
        self.completed_calls.append(job_id)

    def mark_failed(self, job_id: str, failure: AnalysisFailure) -> None:
        self.failed_calls.append((job_id, failure))


class _FakeRunRepository:
    def __init__(self, run: AnalysisRun | None) -> None:
        self._run = run

    def get(self, run_id: str) -> AnalysisRun | None:
        return self._run


class _FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int, int]] = []
        self.should_raise: Exception | None = None

    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None:
        if self.should_raise is not None:
            raise self.should_raise
        self.calls.append((run_id, len(attempts), len(locations), len(artifacts)))


class _FakeCleanup:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def clean_run_temporaries(self, video_id: str, run_id: str, *, preserve_diagnostics: bool) -> None:
        self.calls.append((video_id, run_id, preserve_diagnostics))


class _PassStage:
    """Stage that returns context unchanged."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        return ctx


class _FrameCountStage:
    """Stage that sets a specific frame_count on the context."""

    def __init__(self, frame_count: int) -> None:
        self._frame_count = frame_count

    def run(self, ctx: PipelineContext) -> PipelineContext:
        return replace(ctx, frame_count=self._frame_count)


class _FailStage:
    """Stage that raises PipelineStageError."""

    def __init__(self, message: str = "boom", category: str = "STAGE_FAILED") -> None:
        self._message = message
        self._category = category

    def run(self, ctx: PipelineContext) -> PipelineContext:
        raise PipelineStageError(self._message, self._category)


class _RuntimeFailStage:
    """Stage that raises a plain RuntimeError (not PipelineStageError)."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        raise RuntimeError("unexpected error")


class _ArtifactStage:
    """Stage that appends a fake artifact to the context."""

    def __init__(self, artifact: Artifact) -> None:
        self._artifact = artifact

    def run(self, ctx: PipelineContext) -> PipelineContext:
        return replace(ctx, artifacts=(*ctx.artifacts, self._artifact))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_JOB_ID = "job-1"
_RUN_ID = "run-1"
_VIDEO_ID = "video-1"


def _run(
    *,
    backend_name: str = "opencv",
    backend_version: str = "4.8.0",
    configuration: JsonObject | None = None,
) -> AnalysisRun:
    return AnalysisRun(
        id=_RUN_ID,
        video_id=_VIDEO_ID,
        status=RunStatus.PENDING,
        backend_name=backend_name,
        backend_version=backend_version,
        configuration=configuration or {},
        progress=0.0,
        stage=AnalysisStage.VALIDATING,
        started_at=_T0,
    )


def _message() -> QueueMessage:
    return QueueMessage(job_id=_JOB_ID, video_id=_VIDEO_ID, run_id=_RUN_ID)


_SPEC = StageSpec(AnalysisStage.VALIDATING, 0.00, 0.05)
_SPEC2 = StageSpec(AnalysisStage.PREPROCESSING, 0.05, 0.15)
_SPEC3 = StageSpec(AnalysisStage.SEGMENTING_CAMERA, 0.15, 0.25)


def _orchestrator(
    *,
    run: AnalysisRun | None = None,
    stages: list[tuple[StageSpec, PipelineStageRunner]] | None = None,
    cleanup: _FakeCleanup | None = None,
    publisher: _FakePublisher | None = None,
    job_service: _FakeJobService | None = None,
    clock: _StepClock | None = None,
) -> tuple[AnalysisPipelineOrchestrator, _FakeJobService, _FakePublisher, _FakeCleanup]:
    js = job_service or _FakeJobService()
    pub = publisher or _FakePublisher()
    cl = cleanup or _FakeCleanup()
    r = run if run is not None else _run()
    st: list[tuple[StageSpec, PipelineStageRunner]] = stages if stages is not None else [(_SPEC, _PassStage())]
    orch = AnalysisPipelineOrchestrator(
        job_service=js,
        run_repository=_FakeRunRepository(r),
        publisher=pub,
        stages=st,
        cleanup=cl,
        clock=clock,
    )
    return orch, js, pub, cl


# ===========================================================================
# PIP-001 — Immutable stage-result and pipeline-context types
# ===========================================================================


def test_stage_result_is_frozen() -> None:
    result = StageResult(stage=AnalysisStage.VALIDATING, duration_seconds=1.0, frame_count=100, metadata={})
    with pytest.raises(AttributeError):
        result.duration_seconds = 2.0  # type: ignore[misc]


def test_pipeline_context_is_frozen() -> None:
    ctx = PipelineContext(
        job_id="j",
        run_id="r",
        video_id="v",
        backend_name="opencv",
        backend_version="4.8",
        configuration={},
    )
    with pytest.raises(AttributeError):
        ctx.frame_count = 999  # type: ignore[misc]


def test_pipeline_context_defaults() -> None:
    ctx = PipelineContext(
        job_id="j",
        run_id="r",
        video_id="v",
        backend_name="opencv",
        backend_version="4.8",
        configuration={},
    )
    assert ctx.source_artifact_id == ""
    assert ctx.segment_ids == ()
    assert ctx.attempts == ()
    assert ctx.locations == ()
    assert ctx.artifacts == ()
    assert ctx.frame_count == 0
    assert ctx.stage_results == ()


# ===========================================================================
# PIP-002 — Context built from run data
# ===========================================================================


def test_context_built_from_run() -> None:
    run = _run(backend_name="mlx", backend_version="3.1.0", configuration={"threshold": 0.8})
    orch, js, pub, _ = _orchestrator(run=run)

    captured: list[PipelineContext] = []

    class _CapturingStage:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            captured.append(ctx)
            return ctx

    orch2 = AnalysisPipelineOrchestrator(
        job_service=js,
        run_repository=_FakeRunRepository(run),
        publisher=pub,
        stages=[(_SPEC, _CapturingStage())],
    )
    orch2.handle(_message())

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.job_id == _JOB_ID
    assert ctx.run_id == _RUN_ID
    assert ctx.video_id == _VIDEO_ID
    assert ctx.backend_name == "mlx"
    assert ctx.backend_version == "3.1.0"
    assert ctx.configuration == {"threshold": 0.8}


def test_missing_run_marks_job_failed() -> None:
    js_spy = _FakeJobService()
    orch = AnalysisPipelineOrchestrator(
        job_service=js_spy,
        run_repository=_FakeRunRepository(None),
        publisher=_FakePublisher(),
        stages=[(_SPEC, _PassStage())],
    )
    orch.handle(_message())

    assert len(js_spy.failed_calls) == 1
    _, failure = js_spy.failed_calls[0]
    assert failure.category == "RUN_NOT_FOUND"
    assert failure.stage is AnalysisStage.VALIDATING


# ===========================================================================
# PIP-003 — Ordered stage execution
# ===========================================================================


def test_stages_run_in_order() -> None:
    order: list[str] = []

    class _TrackStage:
        def __init__(self, name: str) -> None:
            self._name = name

        def run(self, ctx: PipelineContext) -> PipelineContext:
            order.append(self._name)
            return ctx

    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=[
            (_SPEC, _TrackStage("validate")),
            (_SPEC2, _TrackStage("preprocess")),
            (_SPEC3, _TrackStage("segment")),
        ],
    )
    orch.handle(_message())
    assert order == ["validate", "preprocess", "segment"]


def test_all_stages_run_on_success() -> None:
    run_count = [0]

    class _CountStage:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            run_count[0] += 1
            return ctx

    stages = [(spec, _CountStage()) for spec in [_SPEC, _SPEC2, _SPEC3]]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())
    assert run_count[0] == 3


# ===========================================================================
# PIP-004 — Progress updates before and after each stage
# ===========================================================================


def test_progress_before_stage_start() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage())])
    orch.handle(_message())

    # First progress call must be at progress_start for the stage
    assert js.progress_calls[0] == (_JOB_ID, AnalysisStage.VALIDATING, 0.00)


def test_progress_after_stage_end() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage())])
    orch.handle(_message())

    # Second progress call must be at progress_end
    assert (_JOB_ID, AnalysisStage.VALIDATING, 0.05) in js.progress_calls


def test_progress_calls_for_two_stages() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage()), (_SPEC2, _PassStage())])
    orch.handle(_message())

    # 2 stages × 2 calls each = 4 progress calls
    assert len(js.progress_calls) == 4
    assert js.progress_calls[0] == (_JOB_ID, AnalysisStage.VALIDATING, 0.00)
    assert js.progress_calls[1] == (_JOB_ID, AnalysisStage.VALIDATING, 0.05)
    assert js.progress_calls[2] == (_JOB_ID, AnalysisStage.PREPROCESSING, 0.05)
    assert js.progress_calls[3] == (_JOB_ID, AnalysisStage.PREPROCESSING, 0.15)


# ===========================================================================
# PIP-005 — Context threaded between stages (no hidden state)
# ===========================================================================


def test_context_mutation_propagates_between_stages() -> None:
    seen_frame_counts: list[int] = []

    class _ReadFrameCount:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            seen_frame_counts.append(ctx.frame_count)
            return ctx

    stages: list[tuple[StageSpec, PipelineStageRunner]] = [
        (_SPEC, _FrameCountStage(42)),
        (_SPEC2, _ReadFrameCount()),
    ]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())

    assert seen_frame_counts == [42]


def test_artifacts_accumulate_across_stages() -> None:
    now = _T0
    art1 = Artifact(
        id="a1",
        video_id=_VIDEO_ID,
        analysis_run_id=_RUN_ID,
        kind="proxy",
        logical_path="v/r/a1.mp4",
        version="1",
        size_bytes=100,
        created_at=now,
    )
    art2 = Artifact(
        id="a2",
        video_id=_VIDEO_ID,
        analysis_run_id=_RUN_ID,
        kind="replay",
        logical_path="v/r/a2.mp4",
        version="1",
        size_bytes=200,
        created_at=now,
    )
    pub = _FakePublisher()
    stages = [
        (_SPEC, _ArtifactStage(art1)),
        (_SPEC2, _ArtifactStage(art2)),
    ]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=pub,
        stages=stages,
    )
    orch.handle(_message())

    assert len(pub.calls) == 1
    _, n_attempts, n_locations, n_artifacts = pub.calls[0]
    assert n_artifacts == 2


# ===========================================================================
# PIP-006 — Backend name and version passed through context
# ===========================================================================


def test_backend_in_context() -> None:
    captured_ctx: list[PipelineContext] = []

    class _CaptureCtx:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            captured_ctx.append(ctx)
            return ctx

    run = _run(backend_name="sam3", backend_version="3.1.0")
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(run),
        publisher=_FakePublisher(),
        stages=[(_SPEC, _CaptureCtx())],
    )
    orch.handle(_message())

    assert captured_ctx[0].backend_name == "sam3"
    assert captured_ctx[0].backend_version == "3.1.0"


# ===========================================================================
# PIP-007 — Pipeline stops on required stage failure
# ===========================================================================


def test_failure_stops_pipeline_immediately() -> None:
    run_count = [0]

    class _CountAfterFail:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            run_count[0] += 1
            return ctx

    stages: list[tuple[StageSpec, PipelineStageRunner]] = [
        (_SPEC, _FailStage()),
        (_SPEC2, _CountAfterFail()),
        (_SPEC3, _CountAfterFail()),
    ]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())
    assert run_count[0] == 0


def test_failure_records_correct_stage() -> None:
    orch, js, _, _ = _orchestrator(
        stages=[
            (_SPEC, _PassStage()),
            (_SPEC2, _FailStage("bad", "MEDIA_ERROR")),
            (_SPEC3, _PassStage()),
        ]
    )
    orch.handle(_message())

    assert len(js.failed_calls) == 1
    _, failure = js.failed_calls[0]
    assert failure.stage is AnalysisStage.PREPROCESSING
    assert failure.category == "MEDIA_ERROR"


def test_plain_exception_uses_class_name_as_category() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _RuntimeFailStage())])
    orch.handle(_message())

    assert len(js.failed_calls) == 1
    _, failure = js.failed_calls[0]
    assert failure.category == "RuntimeError"


def test_no_completed_on_stage_failure() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _FailStage())])
    orch.handle(_message())
    assert js.completed_calls == []


def test_no_publish_on_stage_failure() -> None:
    orch, _, pub, _ = _orchestrator(stages=[(_SPEC, _FailStage())])
    orch.handle(_message())
    assert pub.calls == []


@pytest.mark.parametrize("fail_at", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_failure_at_every_stage_index(fail_at: int) -> None:
    """Pipeline must stop and mark failed regardless of which stage fails."""
    specs = [
        StageSpec(AnalysisStage.VALIDATING, 0.00, 0.05),
        StageSpec(AnalysisStage.PREPROCESSING, 0.05, 0.15),
        StageSpec(AnalysisStage.SEGMENTING_CAMERA, 0.15, 0.25),
        StageSpec(AnalysisStage.AUTO_CALIBRATING, 0.25, 0.35),
        StageSpec(AnalysisStage.TRACKING, 0.35, 0.60),
        StageSpec(AnalysisStage.DETECTING_SHOTS, 0.60, 0.72),
        StageSpec(AnalysisStage.MAPPING_COURT, 0.72, 0.82),
        StageSpec(AnalysisStage.RENDERING_ARTIFACTS, 0.82, 0.92),
        StageSpec(AnalysisStage.COMPUTING_STATISTICS, 0.92, 0.97),
        StageSpec(AnalysisStage.FINALIZING, 0.97, 1.00),
    ]
    run_flags = [False] * 10

    class _MaybeFailStage:
        def __init__(self, idx: int) -> None:
            self._idx = idx

        def run(self, ctx: PipelineContext) -> PipelineContext:
            run_flags[self._idx] = True
            if self._idx == fail_at:
                raise PipelineStageError("injected failure")
            return ctx

    js = _FakeJobService()
    stages = [(specs[i], _MaybeFailStage(i)) for i in range(10)]
    orch = AnalysisPipelineOrchestrator(
        job_service=js,
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())

    # Stages before fail_at ran; stages after did not
    for i in range(fail_at):
        assert run_flags[i], f"Stage {i} should have run (fail_at={fail_at})"
    for i in range(fail_at + 1, 10):
        assert not run_flags[i], f"Stage {i} should NOT have run (fail_at={fail_at})"
    assert len(js.failed_calls) == 1
    assert js.completed_calls == []


# ===========================================================================
# PIP-008 — Cleanup: preserve diagnostics on failure, discard on success
# ===========================================================================


def test_cleanup_called_on_success_without_preserving_diagnostics() -> None:
    orch, _, _, cl = _orchestrator(stages=[(_SPEC, _PassStage())])
    orch.handle(_message())

    assert len(cl.calls) == 1
    vid, rid, preserve = cl.calls[0]
    assert vid == _VIDEO_ID
    assert rid == _RUN_ID
    assert preserve is False


def test_cleanup_called_on_failure_preserving_diagnostics() -> None:
    orch, _, _, cl = _orchestrator(stages=[(_SPEC, _FailStage())])
    orch.handle(_message())

    assert len(cl.calls) == 1
    _, _, preserve = cl.calls[0]
    assert preserve is True


def test_no_cleanup_when_no_cleanup_port() -> None:
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=[(_SPEC, _PassStage())],
        cleanup=None,
    )
    # Must not raise even with no cleanup port
    orch.handle(_message())


def test_cleanup_called_exactly_once_on_success() -> None:
    orch, _, _, cl = _orchestrator(stages=[(_SPEC, _PassStage()), (_SPEC2, _PassStage())])
    orch.handle(_message())
    assert len(cl.calls) == 1


def test_cleanup_called_exactly_once_on_failure() -> None:
    orch, _, _, cl = _orchestrator(stages=[(_SPEC, _FailStage()), (_SPEC2, _PassStage())])
    orch.handle(_message())
    assert len(cl.calls) == 1


# ===========================================================================
# PIP-009 — Atomic publication of final results
# ===========================================================================


def test_publish_called_after_all_stages() -> None:
    pub = _FakePublisher()
    stages = [(_SPEC, _PassStage()), (_SPEC2, _PassStage())]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=pub,
        stages=stages,
    )
    orch.handle(_message())
    assert len(pub.calls) == 1
    assert pub.calls[0][0] == _RUN_ID


def test_publish_failure_marks_job_failed() -> None:
    pub = _FakePublisher()
    pub.should_raise = OSError("disk full")
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage())], publisher=pub)
    orch.handle(_message())

    assert len(js.failed_calls) == 1
    _, failure = js.failed_calls[0]
    assert failure.category == "OSError"
    assert failure.stage is AnalysisStage.FINALIZING


def test_publish_failure_cleans_with_preserved_diagnostics() -> None:
    pub = _FakePublisher()
    pub.should_raise = OSError("disk full")
    orch, _, _, cl = _orchestrator(stages=[(_SPEC, _PassStage())], publisher=pub)
    orch.handle(_message())

    assert len(cl.calls) == 1
    _, _, preserve = cl.calls[0]
    assert preserve is True


def test_no_mark_completed_on_publish_failure() -> None:
    pub = _FakePublisher()
    pub.should_raise = RuntimeError("publication error")
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage())], publisher=pub)
    orch.handle(_message())
    assert js.completed_calls == []


# ===========================================================================
# PIP-010 — Previous completed run stays visible until publication succeeds
# ===========================================================================


def test_publish_only_called_after_all_stages_complete() -> None:
    """Publisher must not be called until all stages have returned successfully."""
    publish_called_after_n_stages = [0]
    stages_run = [0]

    class _CountingStage:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            stages_run[0] += 1
            return ctx

    class _RecordingPublisher:
        def publish_completed(
            self,
            run_id: str,
            attempts: Sequence[ShotAttempt],
            locations: Sequence[ShotLocation],
            artifacts: Sequence[Artifact],
        ) -> None:
            publish_called_after_n_stages[0] = stages_run[0]

    stages = [(_SPEC, _CountingStage()), (_SPEC2, _CountingStage()), (_SPEC3, _CountingStage())]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_RecordingPublisher(),
        stages=stages,
    )
    orch.handle(_message())

    assert publish_called_after_n_stages[0] == 3


def test_publish_not_called_when_first_stage_fails() -> None:
    """First-stage failure must not publish (prior run keeps its published state)."""
    pub = _FakePublisher()
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=pub,
        stages=[(_SPEC, _FailStage()), (_SPEC2, _PassStage())],
    )
    orch.handle(_message())
    assert pub.calls == []


# ===========================================================================
# PIP-011 — Full restart is a new run (orchestrator isolation)
# ===========================================================================


def test_two_independent_runs_do_not_share_context() -> None:
    seen: list[PipelineContext] = []

    class _CapStage:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            seen.append(ctx)
            return replace(ctx, frame_count=ctx.frame_count + 10)

    run_a = _run()
    run_b = AnalysisRun(
        id="run-2",
        video_id=_VIDEO_ID,
        status=RunStatus.PENDING,
        backend_name="opencv",
        backend_version="4.8.0",
        configuration={},
        progress=0.0,
        stage=AnalysisStage.VALIDATING,
        started_at=_T0,
    )
    msg_a = QueueMessage(job_id="job-1", video_id=_VIDEO_ID, run_id="run-1")
    msg_b = QueueMessage(job_id="job-2", video_id=_VIDEO_ID, run_id="run-2")

    class _MultiRunRepo:
        def get(self, run_id: str) -> AnalysisRun | None:
            return run_a if run_id == "run-1" else run_b

    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_MultiRunRepo(),
        publisher=_FakePublisher(),
        stages=[(_SPEC, _CapStage())],
    )
    orch.handle(msg_a)
    orch.handle(msg_b)

    # Each invocation starts with frame_count=0 (no shared state between runs)
    assert seen[0].frame_count == 0
    assert seen[1].frame_count == 0


# ===========================================================================
# PIP-012 — Stage durations and frame counts recorded in stage_results
# ===========================================================================


def test_stage_results_accumulate() -> None:
    final_ctx: list[PipelineContext] = []

    class _CaptureFinal:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            final_ctx.append(ctx)
            return ctx

    stages: list[tuple[StageSpec, PipelineStageRunner]] = [
        (_SPEC, _PassStage()),
        (_SPEC2, _PassStage()),
        (_SPEC3, _CaptureFinal()),
    ]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())

    # Two stages finished before _CaptureFinal runs
    assert len(final_ctx[0].stage_results) == 2
    assert final_ctx[0].stage_results[0].stage is AnalysisStage.VALIDATING
    assert final_ctx[0].stage_results[1].stage is AnalysisStage.PREPROCESSING


def test_stage_result_records_frame_count() -> None:
    final_ctx: list[PipelineContext] = []

    class _CaptureFinal:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            final_ctx.append(ctx)
            return ctx

    stages: list[tuple[StageSpec, PipelineStageRunner]] = [
        (_SPEC, _FrameCountStage(300)),
        (_SPEC2, _CaptureFinal()),
    ]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
    )
    orch.handle(_message())

    assert final_ctx[0].stage_results[0].frame_count == 300


def test_stage_result_duration_uses_clock() -> None:
    """Stage durations are derived from the injected clock."""
    t_before = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    t_after = datetime(2024, 1, 1, 0, 0, 5, tzinfo=UTC)
    clock = _StepClock([t_before, t_after])

    final_ctx: list[PipelineContext] = []

    class _CaptureFinal:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            final_ctx.append(ctx)
            return ctx

    stages = [(_SPEC, _CaptureFinal())]
    orch = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages,
        clock=clock,
    )
    orch.handle(_message())

    # Context captured inside the stage has no stage_results yet;
    # check via final publish by inspecting the full pipeline after
    # The stage_results for the last stage are added AFTER it returns.
    # So we need to capture after: wrap in a second stage.
    final_ctx2: list[PipelineContext] = []

    class _CaptureFinal2:
        def run(self, ctx: PipelineContext) -> PipelineContext:
            final_ctx2.append(ctx)
            return ctx

    clock2 = _StepClock([t_before, t_after, t_before])
    stages2: list[tuple[StageSpec, PipelineStageRunner]] = [(_SPEC, _PassStage()), (_SPEC2, _CaptureFinal2())]
    orch2 = AnalysisPipelineOrchestrator(
        job_service=_FakeJobService(),
        run_repository=_FakeRunRepository(_run()),
        publisher=_FakePublisher(),
        stages=stages2,
        clock=clock2,
    )
    orch2.handle(_message())

    assert len(final_ctx2[0].stage_results) == 1
    assert final_ctx2[0].stage_results[0].duration_seconds == 5.0


# ===========================================================================
# PIP-013 — mark_completed called on full success
# ===========================================================================


def test_mark_completed_called_on_success() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _PassStage())])
    orch.handle(_message())
    assert js.completed_calls == [_JOB_ID]


def test_mark_completed_not_called_on_failure() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _FailStage())])
    orch.handle(_message())
    assert js.completed_calls == []


def test_pipeline_stage_error_category_propagates() -> None:
    orch, js, _, _ = _orchestrator(stages=[(_SPEC, _FailStage("msg", "TRACKING_BACKEND_UNAVAILABLE"))])
    orch.handle(_message())
    _, failure = js.failed_calls[0]
    assert failure.category == "TRACKING_BACKEND_UNAVAILABLE"
    assert failure.message == "msg"
