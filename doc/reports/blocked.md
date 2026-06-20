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

- **Date:** 2026-06-20
- **Module:** Artifact Rendering
- **Blocked item:** Real-video visual-regression comparison beyond deterministic
  overlay-frame SVG fixtures.
- **Status:** Deterministic overlay regression and generated-video encode/decode
  smoke coverage are implemented; human-approved real-video snapshot
  comparison remains blocked.
- **Reason:** The repository does not contain approved ground-truth annotated
  video frames or snapshot images for representative real media.
- **Verified with:** Artifact Rendering tests compare deterministic SVG output
  and render a generated one-second H.264/AAC source through real OpenCV and
  FFmpeg. The decoded output has changed pixels in the overlay region, expected
  duration and dimensions, and retained audio. No human-approved real-video
  baseline files are present in the repository.
- **Impact:** Rendering mechanics, visual overlay placement, sequential decode,
  media encode, and audio retention are covered without external fixtures. No
  claim is made that a real basketball video visually matches a human-approved
  baseline frame.
- **Unblock condition:** Add authorized representative source media plus
  approved annotated-frame snapshots, then compare decoded rendered frames
  against those baselines in the artifact rendering test suite.

## Docker/Colima Smoke Test

- **Date:** 2026-06-20
- **Module:** Release Gate
- **Blocked item:** Docker/Colima runtime smoke.
- **Status:** Static configuration passes, and Colima started successfully, but
  the image build and service runtime smoke did not complete.
- **Verified environment:** Docker CLI 29.5.3; Colima using the macOS
  Virtualization Framework with an `aarch64` Docker 29.5.2 daemon; standalone
  Docker Compose 5.1.4; `docker-compose config --quiet` passed.
- **Build attempt:** `./scripts/docker-smoke.sh` reached the Compose build and
  failed before creating containers with
  `docker-credential-desktop: executable file not found in $PATH`. The global
  Docker client configuration still contains `"credsStore": "desktop"` from a
  removed Docker Desktop installation. Compose also reported that Buildx was
  missing; Homebrew `docker-buildx` 0.35.0 was subsequently installed, but the
  build was not retried before runtime cleanup.
- **Cleanup:** No Compose resources existed, and `colima stop` completed
  successfully. No Docker or Colima command remains running for this test.
- **Impact:** The Dockerfile and two-service Compose model are statically
  validated, but image installation, container startup, web health, worker
  heartbeat, and shared-volume behavior remain unverified.
- **Unblock condition:** Remove or replace the stale Docker Desktop credential
  helper configuration (or use an isolated Docker client configuration), start
  Colima, and rerun `./scripts/docker-smoke.sh` through successful cleanup.
