# ShotSight 2.0 Handoff

Last updated: 2026-06-19

## Repository

- Local main workspace: `/Users/hailiu/Desktop/Projects/shotsight2.0`
- Module worktrees: `/Users/hailiu/Desktop/Projects/shotsight2-worktrees`
- Remote main is expected to track `origin/main`.
- Active development follows `doc/prompt.md`: one module branch/worktree at a time when dependencies conflict, or parallel branches/worktrees when independent.

## Current Main State

`main` is clean and pushed through:

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

The following modules are partially complete or blocked:

- Tracking: OpenCV fallback and interfaces are implemented; real MLX/SAM validation is blocked by missing authorized local model/runtime.
- Shot Lifecycle: implementation and tests are complete; real-video precision/recall benchmark is blocked by missing ground-truth shot-event labels.
- Outcome Classification: implementation and tests are complete; real-video accuracy/calibration benchmark is blocked by missing ground-truth make/miss labels.

See `doc/reports/blocked.md` for the formal blocker entries.

## Active Unmerged Work

Artifact Rendering is implemented on:

- Branch: `codex/artifact-rendering`
- Worktree: `/Users/hailiu/Desktop/Projects/shotsight2-worktrees/artifact-rendering`
- Commit: `62ee21d Implement artifact rendering module`

Diff summary from `main...codex/artifact-rendering`:

- `src/shotsight2/domain/rendering.py`
- `src/shotsight2/services/artifact_rendering.py`
- `tests/artifact_rendering/test_artifact_rendering.py`
- `doc/tasks/artifact-rendering.md`
- `doc/tasks/progress.md`
- `doc/reports/blocked.md`
- `doc/reports/test-report.md`

Subagent validation reported:

- `pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80`: 216 passed, 91.25% coverage
- `mypy --strict src tests`: passed
- `ruff check src tests scripts`: passed
- `ruff format --check src tests scripts`: passed
- `git diff --check main...HEAD`: passed

Do not merge this branch blindly. During review, one issue was found:

- Replay destination filenames are derived from sanitized attempt IDs. Two distinct attempt IDs can theoretically sanitize to the same filename, which could cause destination collisions. Add an explicit duplicate destination check while all outputs are still staged, before any artifact is promoted.

Suggested patch location:

- Add `_ensure_unique_destinations(staged)` before checking destination existence in `ArtifactRenderingService.render_run`.
- Implement `_ensure_unique_destinations(staged: Sequence[_StagedRenderedArtifact]) -> None` near the other private helpers.
- Add a regression test with two attempts whose IDs sanitize to the same replay filename.

After patching, rerun:

```sh
cd /Users/hailiu/Desktop/Projects/shotsight2-worktrees/artifact-rendering
COVERAGE_FILE=/private/tmp/shotsight2-artifact-rendering.coverage PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80
PYTHONPATH=src /Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/mypy --strict src tests
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff check src tests scripts
/Users/hailiu/Desktop/Projects/shotsight2.0/.venv/bin/ruff format --check src tests scripts
git diff --check main...HEAD
```

If those pass:

```sh
cd /Users/hailiu/Desktop/Projects/shotsight2.0
git merge --no-ff codex/artifact-rendering -m "Merge artifact rendering module"
COVERAGE_FILE=/private/tmp/shotsight2-main-artifact-rendering.coverage PYTHONPATH=src .venv/bin/pytest -q --cov=shotsight2 --cov-report=term-missing --cov-fail-under=80
PYTHONPATH=src .venv/bin/mypy --strict src tests
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
git push origin main
```

## Recommended Next Module

After Artifact Rendering is merged, implement the Review module next.

Reason:

- It depends on attempts, players, calibration/location/statistics, and generated artifacts, all of which now exist or are ready after Artifact Rendering.
- It lets users manually correct shooter identity, shot outcome, shot type, and location before the final orchestrator and UI are wired.

Expected branch/worktree:

```sh
cd /Users/hailiu/Desktop/Projects/shotsight2.0
git worktree add ../shotsight2-worktrees/review -b codex/review main
```

Use:

- `doc/tasks/review.md`
- `doc/proposal.md`
- `doc/detailed-design.md`
- `doc/prompt.md`

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

- Real MLX/SAM tracking validation requires authorized local model/runtime.
- Shot lifecycle precision/recall requires ground-truth shot-event labels.
- Outcome classification accuracy/calibration requires ground-truth make/miss labels.
- Artifact Rendering real-video visual regression requires approved baseline snapshots.

## Handoff Priorities

1. Commit and push this handoff note on `main`.
2. Push `codex/artifact-rendering` so the implementation branch is available remotely.
3. Patch the Artifact Rendering duplicate destination issue.
4. Rerun all Artifact Rendering gates.
5. Merge Artifact Rendering into `main` and push.
6. Start Review module on `codex/review`.
7. Continue with Analysis Pipeline Orchestrator, then Application API, then Presentation.
