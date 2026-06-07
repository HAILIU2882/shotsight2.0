"""Deterministic policy for selecting a locally available tracking backend."""

from __future__ import annotations

from collections.abc import Iterable

from shotsight2.adapters.backend_probes import BackendRegistry, inspect_system_profile
from shotsight2.domain.tracking_backends import (
    BackendCapabilityStatus,
    BackendHealth,
    BackendSelectionResult,
    SystemProfile,
    TrackingBackendName,
)


class BackendSelectionError(RuntimeError):
    """Raised when a requested or compatible tracking backend is unavailable."""


class TrackingBackendSelector:
    """Select a backend from capability reports using the approved policy."""

    def __init__(self, registry: BackendRegistry) -> None:
        self._registry = registry

    def select(
        self,
        system: SystemProfile,
        requested_backend: TrackingBackendName | str | None = None,
    ) -> BackendSelectionResult:
        """Probe registered backends and select one deterministic result."""
        health = self._registry.probe_all(system)
        return self.select_from_health(system, health, requested_backend)

    def select_from_health(
        self,
        system: SystemProfile,
        health: Iterable[BackendHealth],
        requested_backend: TrackingBackendName | str | None = None,
    ) -> BackendSelectionResult:
        """Select from an existing report so health endpoints avoid probing twice."""
        reports = tuple(health)
        by_name = {report.name: report for report in reports}
        requested = _parse_requested_backend(requested_backend)

        if requested is not None:
            report = by_name.get(requested)
            if report is None:
                raise BackendSelectionError(f"Requested tracking backend '{requested.value}' is not registered.")
            if not report.is_ready:
                raise BackendSelectionError(
                    f"Requested tracking backend '{requested.value}' is unavailable: {report.reason}"
                )
            return BackendSelectionResult(
                selected=report,
                requested_backend=requested,
                fallback_reasons=(),
                considered_backends=reports,
            )

        policy = (
            (TrackingBackendName.MLX_SAM3, TrackingBackendName.OPENCV_CPU)
            if system.is_apple_silicon
            else (TrackingBackendName.SAM3_CUDA, TrackingBackendName.OPENCV_CPU)
        )
        fallback_reasons: list[str] = []
        for backend_name in policy:
            report = by_name.get(backend_name)
            if report is None:
                fallback_reasons.append(f"{backend_name.value} is not registered.")
                continue
            if report.is_ready:
                return BackendSelectionResult(
                    selected=report,
                    requested_backend=None,
                    fallback_reasons=tuple(fallback_reasons),
                    considered_backends=reports,
                )
            fallback_reasons.append(f"{report.display_name} unavailable: {report.reason}")

        reason = " ".join(fallback_reasons) or "No tracking backends are registered."
        raise BackendSelectionError(f"No compatible tracking backend is available. {reason}")


def build_backend_capability_status(
    registry: BackendRegistry,
    *,
    system: SystemProfile | None = None,
    requested_backend: TrackingBackendName | str | None = None,
) -> BackendCapabilityStatus:
    """Build route-neutral health data for the future `/health` API adapter."""
    current_system = system or inspect_system_profile()
    reports = registry.probe_all(current_system)
    selector = TrackingBackendSelector(registry)
    try:
        selection = selector.select_from_health(
            current_system,
            reports,
            requested_backend=requested_backend,
        )
    except BackendSelectionError as error:
        return BackendCapabilityStatus(
            system=current_system,
            backends=reports,
            selected_backend=None,
            selection_error=str(error),
        )
    return BackendCapabilityStatus(
        system=current_system,
        backends=reports,
        selected_backend=selection.selected.name,
        selection_error=None,
    )


def _parse_requested_backend(
    requested_backend: TrackingBackendName | str | None,
) -> TrackingBackendName | None:
    if requested_backend is None or isinstance(requested_backend, TrackingBackendName):
        return requested_backend
    try:
        return TrackingBackendName(requested_backend)
    except ValueError as error:
        supported = ", ".join(backend.value for backend in TrackingBackendName)
        raise BackendSelectionError(
            f"Unknown tracking backend '{requested_backend}'. Supported values: {supported}."
        ) from error
