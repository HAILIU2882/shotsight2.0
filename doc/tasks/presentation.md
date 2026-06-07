# Presentation Module Tasks

## Goal

Deliver the server-rendered, bilingual local UI without direct persistence,
filesystem, or computer-vision dependencies.

## Dependencies

Application API, localization resources, artifact streaming endpoints.

## Checklist

- [ ] `PRE-001` Create the presentation package, template directory, static directory, and route registration entrypoint.
- [ ] `PRE-002` Add the shared application shell with navigation, status area, error area, and English as the default locale.
- [ ] `PRE-003` Add English and Chinese translation catalogs plus a locale-switch control.
- [ ] `PRE-004` Render the video library as the root screen using an API-provided view model.
- [ ] `PRE-005` Add the upload form with file selection, size guidance, progress, and validation-error rendering.
- [ ] `PRE-006` Add the video detail page with metadata, latest run state, actions, and artifact links.
- [ ] `PRE-007` Add stage-level analysis progress with polling and terminal success/failure states.
- [ ] `PRE-008` Add camera-segment and calibration review views with editable rim and court points.
- [ ] `PRE-009` Add the player list with automatic labels and inline rename support.
- [ ] `PRE-010` Add the attempt review workflow with next/previous navigation and editable result, shooter, type, and location.
- [ ] `PRE-011` Add shot chart, heatmap, aggregate statistics, replay, and full-video views.
- [ ] `PRE-012` Add tracking-repair point/box prompt controls at a selected timestamp.
- [ ] `PRE-013` Add the deletion inventory and explicit destructive confirmation dialog.
- [ ] `PRE-014` Add responsive and keyboard-accessible states for loading, empty, error, and low-confidence results.
- [ ] `PRE-015` Add presentation tests that prove pages use API/application data only and render both locales.

## Completion Criteria

- [ ] All required workflows are reachable without direct database or filesystem access.
- [ ] English and Chinese UI tests pass.
- [ ] Upload, progress, calibration, review, and deletion journeys pass integration tests.

