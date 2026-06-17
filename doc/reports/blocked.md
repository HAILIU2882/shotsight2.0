# Blocked Work

## Tracking Real MLX/SAM Model Validation

- **Date:** 2026-06-17
- **Module:** Tracking
- **Blocked items:** `TRK-011`, `TRK-012`
- **Status:** Partially blocked; OpenCV fallback, shared tracking contract,
  persistence, orchestration, repair prompts, lazy optional adapter boundaries,
  and evaluation script are implemented and tested.
- **Reason:** The local virtual environment does not contain optional packages
  `mlx_sam3` or `sam3`, and no authorized local model bridge or weights are
  available for real MLX SAM 3 Image or official SAM 3.1 video execution.
- **Verified with:** `importlib.util.find_spec("mlx_sam3")` and
  `importlib.util.find_spec("sam3")`, both returned unavailable.
- **Impact:** The application can start without these optional packages, and
  OpenCV fallback tracking can run. Real MLX keyframe inference and an MLX
  inter-frame tracker benchmark remain incomplete.
- **Unblock condition:** Install a supported MLX SAM 3 Image runtime that
  exposes the ShotSight runtime bridge, provide authorized local weights, then
  run the MLX benchmark against `/Users/hailiu/Desktop/bball_pt2.mov`.
