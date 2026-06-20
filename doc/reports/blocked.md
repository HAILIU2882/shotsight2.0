# Blocked Work

## Shot Lifecycle Precision/Recall Benchmark

- **Date:** 2026-06-21
- **Module:** Shot Lifecycle
- **Blocked item:** `SHT-014`
- **Status:** Local annotation, timestamp matching, export, and comparison
  interfaces are implemented; precision/recall metrics are blocked.
- **Reason:** No authorized ground-truth annotation file has been created.
  Labels are intentionally private and outside Git at
  `/Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json`.
- **Verified with:** Deterministic tests prove the lifecycle evaluator counts
  every release, including `UNOBSERVABLE`, through the shared schema.
- **Impact:** Deterministic lifecycle state-machine scenarios are tested, but
  real-video release-event precision and recall are not claimed.
- **Unblock condition:** Create the authorized private annotation file, export
  automatic attempts for the same video, and run the exact annotate, match, and
  lifecycle evaluation commands in `doc/tasks/shot-lifecycle.md`.

## Outcome Classification Accuracy and Calibration Benchmark

- **Date:** 2026-06-20
- **Module:** Outcome Classification
- **Blocked item:** `OUT-010`
- **Status:** Shared-schema matching and comparison interfaces are implemented;
  make/miss accuracy and uncertainty calibration metrics are blocked.
- **Reason:** No authorized ground-truth labels or matching automatic prediction
  file has been created. Labels remain intentionally outside Git.
- **Verified with:** Deterministic tests prove `UNOBSERVABLE` labels are reported
  with an explicit excluded count and omitted from outcome metrics.
- **Impact:** Deterministic outcome classification scenarios are tested, but
  real-video make/miss accuracy and confidence calibration are not claimed.
- **Unblock condition:** Complete the private annotation and matching workflow,
  then run the exact outcome command in `doc/tasks/outcome-classification.md`.

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

## Resolved: Docker/Colima Smoke Test

- **Date:** 2026-06-20
- **Module:** Release Gate
- **Status:** Resolved. The CPU image built and both Compose services passed
  their runtime healthchecks.
- **Verified environment:** Docker CLI 29.5.3; Colima using the macOS
  Virtualization Framework with an `aarch64` Docker 29.5.2 daemon; standalone
  Docker Compose 5.1.4; `docker-compose config --quiet` passed.
- **Initial failure and fix:** The first isolated build succeeded, but both
  services restarted with `MigrationError` because repository SQL migrations
  were absent from the installed image. All six SQL files now live under the
  installable `shotsight2/migrations` package, and `SQLiteDatabase` resolves
  that package-relative path without depending on a Python installation
  layout. The top-level duplicate was removed.
- **Successful command:** `DOCKER_CONFIG=<isolated-temp-dir>
  ./scripts/docker-smoke.sh`. The temporary Docker config contained plugin
  discovery and no credential store; the user's global Docker config was not
  changed.
- **Runtime evidence:** The image installed FFmpeg, NumPy, OpenCV headless, and
  Pillow; Hatch built and installed a wheel containing the package migration
  resources; the `web` and standard production `shotsight-worker` containers
  both migrated the shared database and became healthy; HTTP `/health` returned
  200 with FFmpeg available and `opencv-cpu` selected and ready; HTTP `/ready`
  returned 200 with the database and queue available and the production worker
  ready; the worker's SQLite heartbeat healthcheck passed against the shared
  `shotsight-data` volume.
- **Cleanup:** The smoke script removed both containers, the network, and the
  named volume. The Docker runtime release gate is no longer blocked.
