# Architecture Notes

The initial architecture is local-first and separates product rules from
computer-vision implementations:

- `domain`: shot attempts, outcomes, players, court coordinates, and review.
- `services`: ingestion, calibration, tracking orchestration, lifecycle
  classification, replay generation, and statistics.
- `adapters`: FFmpeg, SQLite, filesystem storage, SAM 3, and fallback trackers.

SAM 3 must be behind a tracking interface. The official implementation currently
assumes CUDA, while ShotSight must also operate on macOS, Windows, and Linux
machines without paid cloud GPU services. A technical spike must establish the
supported local backends before the production tracking adapter is selected.

