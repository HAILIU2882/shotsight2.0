# Tracking Backend Selection Module Tasks

## Goal

Select the best locally available tracking backend and explain every fallback.

## Dependencies

Tracking backend registry, platform inspection, model store, configuration.

## Checklist

- [x] `BKS-001` Define backend capability, device, health, and selection-result types.
- [x] `BKS-002` Create a backend registry that does not import optional model packages eagerly.
- [x] `BKS-003` Detect operating system, architecture, available memory, and Python runtime.
- [x] `BKS-004` Detect Apple Silicon and MLX runtime/model readiness.
- [x] `BKS-005` Detect supported NVIDIA GPU, CUDA runtime, and official SAM 3.1 readiness.
- [x] `BKS-006` Detect CPU fallback readiness.
- [x] `BKS-007` Implement the confirmed Apple, NVIDIA, then fallback selection policy.
- [x] `BKS-008` Validate requested backend overrides against actual capabilities.
- [x] `BKS-009` Record backend name, version, model, device, and configuration in the analysis run.
- [x] `BKS-010` Return user-readable reasons when a preferred backend is unavailable.
- [x] `BKS-011` Add tests with mocked Apple, NVIDIA, CPU-only, missing-model, and unhealthy-backend environments.
- [x] `BKS-012` Expose capability status through `/health`.

## Completion Criteria

- [x] Core application import works with no AI packages installed.
- [x] Selection is deterministic for a given capability report.
- [x] Every fallback is visible and recorded.

## Evidence

- `/health` returns system details, every probed backend's capabilities and
  readiness reason, the selected backend, and any override or selection error.
- Optional MLX, PyTorch, SAM 3, and OpenCV imports remain deferred until the
  health request executes its capability probes.
- The full test suite passes with 12 tests and 92.48% coverage, above the
  required 80%.
- `mypy --strict src tests` passes; full-repository Ruff lint and format checks
  pass.
