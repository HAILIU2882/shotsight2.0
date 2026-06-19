"""Analysis pipeline orchestrator: ordered, observable, atomic, replaceable stages."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from shotsight2.domain.jobs import QueueMessage
from shotsight2.domain.persistence import (
    AnalysisRun,
    AnalysisStage,
    Artifact,
    JsonObject,
    ShotAttempt,
    ShotLocation,
)
from shotsight2.services.analysis_jobs import AnalysisFailure

LOGGER = logging.getLogger("shotsight2.pipeline")


@dataclass(frozen=True, slots=True)
class StageResult:
    """Immutable timing and telemetry for one completed pipeline stage."""

    stage: AnalysisStage
    duration_seconds: float
    frame_count: int
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class PipelineContext:
    """Identifiers and accumulated results passed between stages without hidden state."""

    job_id: str
    run_id: str
    video_id: str
    backend_name: str
    backend_version: str
    configuration: JsonObject
    source_artifact_id: str = ""
    segment_ids: tuple[str, ...] = ()
    attempts: tuple[ShotAttempt, ...] = ()
    locations: tuple[ShotLocation, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    frame_count: int = 0
    stage_results: tuple[StageResult, ...] = ()


class PipelineStageRunner(Protocol):
    """A single replaceable, independently testable pipeline stage."""

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Execute stage logic and return an updated context."""
        ...


@dataclass(frozen=True, slots=True)
class StageSpec:
    """Ordered progress bounds for one named pipeline stage."""

    stage: AnalysisStage
    progress_start: float
    progress_end: float


class JobProgressPort(Protocol):
    """Narrow job-service interface required by the pipeline orchestrator."""

    def update_progress(self, job_id: str, stage: AnalysisStage, progress: float) -> object:
        """Persist monotonic progress for a running job."""
        ...

    def mark_completed(self, job_id: str) -> object:
        """Record successful completion of a running job."""
        ...

    def mark_failed(self, job_id: str, failure: AnalysisFailure) -> object:
        """Durably persist a structured failure on the job and its run."""
        ...


class RunReaderPort(Protocol):
    """Narrow repository interface for loading analysis run configuration."""

    def get(self, run_id: str) -> AnalysisRun | None:
        """Return a run by identifier, or None when absent."""
        ...


class PublishPort(Protocol):
    """Atomic publication of completed analysis results."""

    def publish_completed(
        self,
        run_id: str,
        attempts: Sequence[ShotAttempt],
        locations: Sequence[ShotLocation],
        artifacts: Sequence[Artifact],
    ) -> None:
        """Atomically commit run results and mark the run published."""
        ...


class TempCleanupPort(Protocol):
    """Remove per-run temporary artifacts after pipeline completion or failure."""

    def clean_run_temporaries(
        self,
        video_id: str,
        run_id: str,
        *,
        preserve_diagnostics: bool,
    ) -> None:
        """Delete temporary files for (video_id, run_id).

        When preserve_diagnostics is True, diagnostic artifacts survive.
        Prior completed runs are never touched.
        """
        ...


DEFAULT_STAGE_SPECS: tuple[StageSpec, ...] = (
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
)


class PipelineStageError(RuntimeError):
    """Raised by a pipeline stage to signal a structured failure with a category code."""

    def __init__(self, message: str, category: str = "STAGE_FAILED") -> None:
        super().__init__(message)
        self.category = category


class AnalysisPipelineOrchestrator:
    """Wire ordered injectable stages with progress tracking, publication, and cleanup."""

    def __init__(
        self,
        *,
        job_service: JobProgressPort,
        run_repository: RunReaderPort,
        publisher: PublishPort,
        stages: Sequence[tuple[StageSpec, PipelineStageRunner]],
        cleanup: TempCleanupPort | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._job_service = job_service
        self._run_repository = run_repository
        self._publisher = publisher
        self._stages = list(stages)
        self._cleanup = cleanup
        self._clock = clock or (lambda: datetime.now(UTC))

    def handle(self, message: QueueMessage) -> None:
        """Execute the full analysis pipeline for one queued job.

        Stages run in declaration order; any stage failure stops the pipeline,
        records a structured failure, and cleans temporary artifacts while
        preserving prior completed runs and diagnostic artifacts.
        """
        run = self._run_repository.get(message.run_id)
        if run is None:
            failure = AnalysisFailure(
                category="RUN_NOT_FOUND",
                message=f"Analysis run {message.run_id} not found",
                stage=AnalysisStage.VALIDATING,
            )
            self._job_service.mark_failed(message.job_id, failure)
            return

        ctx = PipelineContext(
            job_id=message.job_id,
            run_id=message.run_id,
            video_id=message.video_id,
            backend_name=run.backend_name,
            backend_version=run.backend_version,
            configuration=run.configuration,
        )

        for spec, runner in self._stages:
            self._job_service.update_progress(ctx.job_id, spec.stage, spec.progress_start)

            stage_start = self._clock()
            try:
                ctx = runner.run(ctx)
            except Exception as exc:
                category = exc.category if isinstance(exc, PipelineStageError) else type(exc).__name__
                failure = AnalysisFailure(
                    category=category,
                    message=str(exc),
                    stage=spec.stage,
                )
                LOGGER.error(
                    "pipeline_stage_failed",
                    extra={
                        "job_id": ctx.job_id,
                        "run_id": ctx.run_id,
                        "stage": spec.stage.value,
                        "error": str(exc),
                    },
                )
                self._job_service.mark_failed(ctx.job_id, failure)
                self._do_cleanup(ctx, preserve_diagnostics=True)
                return

            duration = (self._clock() - stage_start).total_seconds()
            result = StageResult(
                stage=spec.stage,
                duration_seconds=duration,
                frame_count=ctx.frame_count,
                metadata={},
            )
            ctx = replace(ctx, stage_results=(*ctx.stage_results, result))
            self._job_service.update_progress(ctx.job_id, spec.stage, spec.progress_end)

        # PIP-009/PIP-010: publish atomically; prior run stays visible until this succeeds
        try:
            self._publisher.publish_completed(
                ctx.run_id,
                ctx.attempts,
                ctx.locations,
                ctx.artifacts,
            )
        except Exception as exc:
            failure = AnalysisFailure(
                category=type(exc).__name__,
                message=str(exc),
                stage=AnalysisStage.FINALIZING,
            )
            self._job_service.mark_failed(ctx.job_id, failure)
            self._do_cleanup(ctx, preserve_diagnostics=True)
            return

        self._job_service.mark_completed(ctx.job_id)
        self._do_cleanup(ctx, preserve_diagnostics=False)
        LOGGER.info("pipeline_completed", extra={"job_id": ctx.job_id, "run_id": ctx.run_id})

    def _do_cleanup(self, ctx: PipelineContext, *, preserve_diagnostics: bool) -> None:
        if self._cleanup is not None:
            self._cleanup.clean_run_temporaries(
                ctx.video_id,
                ctx.run_id,
                preserve_diagnostics=preserve_diagnostics,
            )
