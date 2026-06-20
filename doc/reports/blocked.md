# Blocked Work

## Shot Lifecycle Precision/Recall Benchmark

- **Date:** 2026-06-18
- **Module:** Shot Lifecycle
- **Blocked item:** `SHT-014`
- **Status:** Benchmark comparison interface implemented; precision/recall
  metrics are blocked.
- **Reason:** No ground-truth shot-event annotation file exists in the
  repository or documented local fixtures.
- **Verified with:** `scripts/evaluate_shot_lifecycle.py` reports
  `status: blocked` when annotations and predictions are not supplied.
- **Impact:** Deterministic lifecycle state-machine scenarios are tested, but
  real-video release-event precision and recall are not claimed.
- **Unblock condition:** Add an authorized annotation file containing expected
  shot release timestamps, generate lifecycle predictions for the same source,
  then run `scripts/evaluate_shot_lifecycle.py --annotations ... --predictions ...`.

## Outcome Classification Accuracy and Calibration Benchmark

- **Date:** 2026-06-18
- **Module:** Outcome Classification
- **Blocked item:** `OUT-010`
- **Status:** Benchmark comparison interface implemented; make/miss accuracy
  and uncertainty calibration metrics are blocked.
- **Reason:** No ground-truth make/miss outcome label file and matching
  automatic prediction file exist in the repository or documented local
  fixtures.
- **Verified with:** `scripts/evaluate_outcome_classification.py` reports
  `status: blocked` when labels and predictions are not supplied, and repository
  search found no outcome label fixture.
- **Impact:** Deterministic outcome classification scenarios are tested, but
  real-video make/miss accuracy and confidence calibration are not claimed.
- **Unblock condition:** Add an authorized label file containing expected
  `MADE`/`MISSED` outcomes and generated automatic predictions for the same
  attempt IDs, then run
  `scripts/evaluate_outcome_classification.py --labels ... --predictions ...`.

## Artifact Rendering Real-Video Visual Regression

- **Date:** 2026-06-19
- **Module:** Artifact Rendering
- **Blocked item:** Real-video visual-regression comparison beyond deterministic
  overlay-frame SVG fixtures.
- **Status:** Deterministic overlay frame regression is implemented and tested;
  real-video snapshot comparison is blocked.
- **Reason:** The repository does not contain approved ground-truth annotated
  video frames or snapshot images for representative real media.
- **Verified with:** Artifact Rendering tests compare deterministic SVG overlay
  output from stored observations; no real-video visual baseline files are
  present in the repository.
- **Impact:** Rendering logic, artifact staging, metadata, localization, and
  media encode boundaries are covered, but no claim is made that a real encoded
  video visually matches a human-approved baseline frame.
- **Unblock condition:** Add authorized representative source media plus
  approved annotated-frame snapshots, then compare decoded rendered frames
  against those baselines in the artifact rendering test suite.

## Docker/Colima Smoke Test

- **Date:** 2026-06-19
- **Module:** Release Gate
- **Blocked item:** Docker/Colima runtime smoke.
- **Status:** Docker CLI and Colima are installed, but the Colima daemon is not
  running.
- **Reason:** `docker build -t shotsight2-smoke:local .` failed because Docker
  could not connect to `/Users/hailiu/.colima/default/docker.sock`.
- **Verified with:** `docker --version` returned Docker version 29.5.3;
  `which colima` returned `/opt/homebrew/bin/colima`; `colima status` returned
  `colima is not running`.
- **Impact:** Dockerfile contents can be inspected, but Docker image build/run
  smoke cannot be claimed in the current local runtime state.
- **Unblock condition:** Start Colima or another Docker daemon, then run
  `docker build -t shotsight2-smoke:local .` and a container `/health` smoke.
