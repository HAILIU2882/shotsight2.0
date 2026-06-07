# Tracking Backend Selection Module Tasks

## Goal

Select the best locally available tracking backend and explain every fallback.

## Dependencies

Tracking backend registry, platform inspection, model store, configuration.

## Checklist

- [ ] `BKS-001` Define backend capability, device, health, and selection-result types.
- [ ] `BKS-002` Create a backend registry that does not import optional model packages eagerly.
- [ ] `BKS-003` Detect operating system, architecture, available memory, and Python runtime.
- [ ] `BKS-004` Detect Apple Silicon and MLX runtime/model readiness.
- [ ] `BKS-005` Detect supported NVIDIA GPU, CUDA runtime, and official SAM 3.1 readiness.
- [ ] `BKS-006` Detect CPU fallback readiness.
- [ ] `BKS-007` Implement the confirmed Apple, NVIDIA, then fallback selection policy.
- [ ] `BKS-008` Validate requested backend overrides against actual capabilities.
- [ ] `BKS-009` Record backend name, version, model, device, and configuration in the analysis run.
- [ ] `BKS-010` Return user-readable reasons when a preferred backend is unavailable.
- [ ] `BKS-011` Add tests with mocked Apple, NVIDIA, CPU-only, missing-model, and unhealthy-backend environments.
- [ ] `BKS-012` Expose capability status through `/health`.

## Completion Criteria

- [ ] Core application import works with no AI packages installed.
- [ ] Selection is deterministic for a given capability report.
- [ ] Every fallback is visible and recorded.

