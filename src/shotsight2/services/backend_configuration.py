"""Presentation-safe tracking backend discovery and analysis configuration."""

from __future__ import annotations

from dataclasses import dataclass

from shotsight2.adapters.backend_probes import BackendRegistry
from shotsight2.domain.persistence import JsonObject
from shotsight2.domain.tracking_backends import BackendHealthState, SystemProfile
from shotsight2.services.analysis_jobs import AnalysisConfiguration
from shotsight2.services.tracking_backend_selection import BackendSelectionError, TrackingBackendSelector


@dataclass(frozen=True, slots=True)
class AnalysisBackendOption:
    """One constrained backend choice rendered by the local UI."""

    name: str
    display_name: str
    version: str
    available: bool
    selected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AnalysisBackendCatalog:
    """Backend choices and any configured-default selection error."""

    options: tuple[AnalysisBackendOption, ...]
    selection_error: str | None

    @property
    def has_available_backend(self) -> bool:
        """Return whether the analysis form can be submitted."""

        return any(option.available for option in self.options)


class AnalysisBackendConfigurationService:
    """Probe backends consistently for both form rendering and submission."""

    def __init__(self, registry: BackendRegistry, system: SystemProfile, configured_backend: str | None) -> None:
        self._registry = registry
        self._system = system
        self._configured_backend = configured_backend

    def catalog(self) -> AnalysisBackendCatalog:
        """Return all registered choices with the configured default selected."""

        reports = self._registry.probe_all(self._system)
        selected_name: str | None = None
        selection_error: str | None = None
        try:
            selection = TrackingBackendSelector(self._registry).select_from_health(
                self._system,
                reports,
                requested_backend=self._configured_backend,
            )
            selected_name = selection.selected.name.value
        except BackendSelectionError as error:
            selection_error = str(error)

        return AnalysisBackendCatalog(
            options=tuple(
                AnalysisBackendOption(
                    name=report.name.value,
                    display_name=report.display_name,
                    version=report.version or "unknown",
                    available=report.state is BackendHealthState.READY,
                    selected=report.name.value == selected_name,
                    reason=report.reason,
                )
                for report in reports
            ),
            selection_error=selection_error,
        )

    def resolve(self, backend_name: str) -> AnalysisConfiguration:
        """Validate a submitted choice and capture probed version/provenance."""

        selection = TrackingBackendSelector(self._registry).select(
            self._system,
            requested_backend=backend_name,
        )
        record = selection.to_analysis_record()
        values: JsonObject = dict(record.configuration)
        if record.model is not None:
            values["model"] = record.model
        values["device_type"] = record.device_type
        values["device_name"] = record.device_name
        return AnalysisConfiguration(
            backend_name=record.backend_name,
            backend_version=record.backend_version or "unknown",
            values=values,
        )
