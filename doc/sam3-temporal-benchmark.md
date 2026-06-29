# SAM 3 Temporal Basketball Benchmark

The MLX SAM 3 adapter keeps one active basketball candidate because a game has
one ball. It keeps that single basketball-only memory for up to five missed
inference frames and 0.6 seconds by default. It expands the velocity-predicted
box by 35 percent on each side and supplies at most one positive temporal
geometric prompt alongside the `basketball` concept. New tracks require
confidence 0.5. A live temporal prompt may continue a geometrically consistent
track at confidence 0.325 or greater; the area-change ratio remains bounded at
4.0.

All values are configurable through `ModelConfig.options`:

- `seed_confidence_threshold`
- `continuation_confidence_threshold`
- `continuation_max_area_ratio`
- `association_distance_fraction`
- `temporal_max_gap_frames`
- `temporal_max_gap_seconds`
- `temporal_box_expansion_fraction`

Keep human labels and generated reports outside Git. The focused evaluator
seeks only selected labeled windows and uses OpenCV for frame decoding only:

```sh
PYTHONPATH=src:vendor/mlx_sam3 .venv-mlx/bin/python scripts/evaluate_tracking.py \
  --video /Users/hailiu/Desktop/bball_pt2.mov \
  --backend mlx-sam3 \
  --shot-labels /absolute/private/path/annotations.json \
  --shot-id shot-003 \
  --sampling-fps 10 \
  --window-before-seconds 0.8 \
  --window-after-seconds 1.0 \
  --output /absolute/private/path/temporal-shot-003.json
```

For a concept-only comparison on the same frames, add
`--temporal-max-gap-frames 0 --temporal-max-gap-seconds 0`. The report separates
overall frame coverage, symmetric release-window frame coverage, and
post-release frame coverage. It does not run shot lifecycle or claim attempt
detection.

## Local Shot-003 Run After Single-Candidate Bounding

Date: 2026-06-29

Command:

```sh
PYTHONPATH=src:/Users/hailiu/Desktop/Projects/shotsight2.0/vendor/mlx_sam3 \
  /Users/hailiu/Desktop/Projects/shotsight2.0/.venv-mlx/bin/python \
  scripts/evaluate_tracking.py \
  --video /Users/hailiu/Desktop/bball_pt2.mov \
  --backend mlx-sam3 \
  --shot-labels /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/annotations.json \
  --shot-id shot-003 \
  --sampling-fps 10 \
  --window-before-seconds 0.8 \
  --window-after-seconds 1.0 \
  --output /Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/shot-003-temporal.json
```

Result written to
`/Users/hailiu/Desktop/shotsight2-benchmarks/bball_pt2/shot-003-temporal.json`.

- Evaluated shots: 1 (`shot-003`)
- Evaluated frames: 18
- Observed frames: 17
- Basketball observations: 17
- Basketball track IDs: 1 (`basketball-1`)
- Identity switches: 0
- Ball track coverage: 0.9444444444444444
- Release-window hits: 1
- Release-window frame coverage: 1.0
- Post-release hits: 1
- Post-release frame coverage: 1.0
- Elapsed seconds: 14.486560541961808

Reviewer rerun confirmed the same quality metrics: 17 basketball observations,
one basketball track ID, zero identity switches, and full release/post-release
frame coverage.

The run used the default bounded temporal options:

```json
{
  "association_distance_fraction": 0.12,
  "continuation_confidence_threshold": 0.325,
  "continuation_max_area_ratio": 4.0,
  "seed_confidence_threshold": 0.5,
  "temporal_box_expansion_fraction": 0.35,
  "temporal_max_gap_frames": 5,
  "temporal_max_gap_seconds": 0.6
}
```
