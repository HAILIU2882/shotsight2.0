# ShotSight 2.0 Handoff

Last updated: 2026-06-19

## Repository

- Local main workspace: `/Users/hailiu/Desktop/Projects/shotsight2.0`
- Module worktrees: `/Users/hailiu/Desktop/Projects/shotsight2.0/worktrees`
- Remote main is expected to track `origin/main`.
- Active development follows `doc/prompt.md`: one module branch/worktree at a time when dependencies conflict, or parallel branches/worktrees when independent.

## Current Main State

`main` is clean and pushed through:

- `Merge Presentation module`
- `be31278 Merge Application API module`
- `76695dd Merge analysis pipeline orchestrator module`
- `e6e5553 Merge outcome classification module`
- `f39399c Merge shot lifecycle engine`
- `6df87cc Merge track association module`
- `c6e1002 Merge tracking module`

The following modules are complete on `main`:

- Persistence
- Artifact Store
- Media Processing
- Worker Queue
- Tracking Backend Selection
- Video Ingestion
- Analysis Job
- Video Library
- Deletion
- Camera Segment
- Calibration
- Track Association
- Court Mapping
- Statistics
- Review
- Analysis Pipeline Orchestrator
- Application API (63 tests, 94% coverage)
- Presentation (64 tests, 96% coverage)

The following modules are partially complete or blocked:

- Tracking: OpenCV fallback and Apple Silicon MLX SAM 3 image inference are implemented and benchmarked; accuracy still needs ground-truth labels.
- Shot Lifecycle: implementation and tests are complete; real-video precision/recall benchmark is blocked by missing ground-truth shot-event labels.
- Outcome Classification: implementation and tests are complete; real-video accuracy/calibration benchmark is blocked by missing ground-truth make/miss labels.

See `doc/reports/blocked.md` for the formal blocker entries.

## Active Unmerged Work

There is no known intentional unmerged module work on `main`.

The historical external worktree
`/Users/hailiu/Desktop/Projects/shotsight2-worktrees/artifact-rendering` may
contain an interrupted merge from earlier review work. Treat it as stale unless
you intentionally inspect and clean it. Future work should use project-local
worktrees under `/Users/hailiu/Desktop/Projects/shotsight2.0/worktrees`.

Artifact Rendering is already on `main`. The previously identified replay
destination collision issue has been fixed on `main` with a duplicate
destination guard before promotion and a regression test using two attempt IDs
that sanitize to the same replay filename.

## Recommended Next Module

The Presentation module is now complete and merged. All planned modules are on
`main`. The next work items are:

1. Run full quality gates on `main` after the latest Artifact Rendering guard
   and documentation cleanup.
2. Address formal blockers in `doc/reports/blocked.md` as resources become
   available.
3. Run end-to-end local upload, analysis, review, reanalysis, and deletion
   validation.
4. Update release-gate status in `doc/tasks/progress.md`.

## Subagent Setup Instructions

The next AI agent should continue using the multi-agent workflow described in
`doc/prompt.md`.

Main agent responsibilities:

- Keep `main` as the integration branch.
- Read `doc/proposal.md`, `doc/detailed-design.md`, `doc/prompt.md`, and the
  target module file in `doc/tasks/` before assigning work.
- Create one branch and one worktree per module or per corrective task.
- Delegate implementation to a subagent when subagents are available.
- Review every subagent branch before merge.
- Run the full quality gates before and after merge.
- Update progress/report documents only when the evidence supports it.

Subagent responsibilities:

- Work only inside its assigned worktree.
- Implement the whole assigned module checklist or clearly mark blockers.
- Add pytest coverage for the new behavior.
- Keep code compatible with `mypy --strict`, `ruff check`, and
  `ruff format --check`.
- Update the module task file as checklist items are completed.
- Update `doc/reports/test-report.md` with exact validation commands/results.
- Update `doc/reports/blocked.md` if any task cannot be completed.
- Create one module commit with an English commit message.

Recommended worktree pattern:

```sh
cd /Users/hailiu/Desktop/Projects/shotsight2.0
git worktree add worktrees/<module-name> -b codex/<module-name> main
```

Recommended subagent prompt template:

```text
You are implementing the <Module Name> module for ShotSight 2.0.

Workspace:
/Users/hailiu/Desktop/Projects/shotsight2.0/worktrees/<module-name>

Read first:
- doc/proposal.md
- doc/detailed-design.md
- doc/prompt.md
- doc/tasks/<module-name>.md
- doc/tasks/progress.md
- doc/reports/blocked.md
- doc/reports/test-report.md

Rules:
- Work only in this worktree and branch codex/<module-name>.
- Complete the smallest executable tasks listed in doc/tasks/<module-name>.md.
- Add or update pytest tests for every behavior.
- Run:
  PYTHONPATH=src .venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80
  PYTHONPATH=src .venv/bin/mypy --strict src tests
  .venv/bin/ruff check src tests scripts
  .venv/bin/ruff format --check src tests scripts
  git diff --check main...HEAD
- Update doc/tasks/<module-name>.md as items are completed.
- Update doc/reports/test-report.md with exact commands and results.
- If blocked, update doc/reports/blocked.md and continue any unblocked work.
- Commit with one English commit message when complete.
- Do not merge into main. The main agent will review and merge.
```

Parallelism guidance:

- All planned implementation modules are currently present on `main`.
- Use project-local worktrees for any blocker, benchmark, release-gate, or bug
  fix work.
- Prefer one corrective branch per blocker or release-gate item so validation
  and progress updates stay easy to audit.

## Progress Update Rules

For each module:

- Update only that module file in `doc/tasks/<module-name>.md` as each checklist item is truly completed.
- Update `doc/tasks/progress.md` only when the full module meets its completion criteria.
- Add validation results to `doc/reports/test-report.md`.
- Add unresolved blockers to `doc/reports/blocked.md`.
- Add architectural deviations to `doc/reports/architecture-deviations.md`.
- Add durable technical decisions to `doc/reports/decision-log.md`.

A module can be marked complete only when:

- All checklist items in its task file are complete.
- Unit and integration tests pass.
- Coverage is at least 80%.
- `mypy --strict` passes.
- `ruff check` passes.
- `ruff format --check` passes.
- Required documentation/report updates are committed.
- The main agent has reviewed the module branch.

## Quality Gates

Use these gates before merging a module branch:

```sh
PYTHONPATH=src .venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80
PYTHONPATH=src .venv/bin/mypy --strict src tests
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
git diff --check main...HEAD
```

Run the same gates again on `main` after merging.

## Known Blockers

Current formal blockers are tracked in `doc/reports/blocked.md`:

- Official SAM 3.1 CUDA tracking validation still requires a compatible NVIDIA host.
- Shot lifecycle precision/recall requires ground-truth shot-event labels.
- Outcome classification accuracy/calibration requires ground-truth make/miss labels.
- Artifact Rendering real-video visual regression requires approved baseline snapshots.

## Handoff Priorities

1. Run full `main` quality gates and record results in
   `doc/reports/test-report.md`.
2. Address the formal blockers in `doc/reports/blocked.md` when the required
   model/runtime or ground-truth labels become available.
3. Execute end-to-end upload, analysis, review, reanalysis, and deletion tests.
4. Update `doc/tasks/progress.md` release gates only when evidence is recorded.
5. Keep future corrective work in project-local `worktrees/<task-name>`
   directories and merge through `main`.
