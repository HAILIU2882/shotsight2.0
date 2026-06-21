# Blocked Work

## Shot Lifecycle Precision/Recall Benchmark

- **Date:** 2026-06-21
- **Module:** Shot Lifecycle
- **Blocked item:** `SHT-014`
- **Status:** The private real-video benchmark was executed, but acceptance
  failed.
- **Reason:** The 15 human-annotated releases had zero automatic attempts and
  zero matches. Recall is `0.0`; precision is unavailable (`null`,
  `precision_defined: false`) because no releases were predicted.
- **Verified with:** MLX SAM3 run `21b94461-123b-4a19-a775-a253812339eb`
  produced 58 basketball observations over 912 frames (`0.064` coverage),
  average ball confidence `0.67`, and zero rim observations. Runtime was
  2026-06-20T21:37:07.873170Z through 2026-06-20T21:52:25.595485Z
  (917.72 seconds) for 91.228 seconds of source video. No OpenCV detector
  metrics are used for this baseline.
- **Impact:** Shot-event precision cannot be measured and recall fails at zero;
  the module checklist remains incomplete and the product is not ready.
- **Unblock condition:** Produce SAM3 automatic release attempts on the private
  benchmark and pass the lifecycle acceptance criteria on a rerun.

## Outcome Classification Accuracy and Calibration Benchmark

- **Date:** 2026-06-21
- **Module:** Outcome Classification
- **Blocked item:** `OUT-010`
- **Status:** The private real-video benchmark was executed, but acceptance
  failed.
- **Reason:** All 15 human outcomes were observable (6 made and 9 missed), but
  the SAM3 run produced zero automatic attempts. There are no matched certain
  predictions, so make/miss accuracy is unavailable (`null`,
  `make_miss_accuracy_defined: false`), not a measured `0%`.
- **Verified with:** The same MLX SAM3 run and lifecycle evidence above; no
  OpenCV detector metrics are used for this baseline.
- **Impact:** Outcome accuracy, uncertainty calibration, and confidence
  calibration cannot be measured; the module checklist remains incomplete and
  the product is not ready.
- **Unblock condition:** Produce matched SAM3 attempts with certain outcome
  predictions and pass outcome accuracy/calibration acceptance on a rerun.

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
