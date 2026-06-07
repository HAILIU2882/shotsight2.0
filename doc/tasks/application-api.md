# Application API Module Tasks

## Goal

Expose stable local HTTP boundaries for presentation and worker status while
keeping infrastructure details private.

## Dependencies

Application services, command/query models, error model, artifact authorization.

## Checklist

- [ ] `API-001` Create API routers and version-neutral request/response schema packages.
- [ ] `API-002` Define shared validation and error response schemas.
- [ ] `API-003` Implement `/health` with web, worker, FFmpeg, storage, and backend capability status.
- [ ] `API-004` Implement video list, upload, detail, and deletion routes.
- [ ] `API-005` Implement analysis start and job-progress routes.
- [ ] `API-006` Implement camera-segment listing and calibration correction routes.
- [ ] `API-007` Implement player listing and rename routes.
- [ ] `API-008` Implement attempt list, create, update, and delete routes.
- [ ] `API-009` Implement tracking-repair prompt submission.
- [ ] `API-010` Implement safe artifact streaming with range-request support.
- [ ] `API-011` Implement language preference update.
- [ ] `API-012` Map domain, validation, dependency, and conflict errors to consistent HTTP responses.
- [ ] `API-013` Add request-size, identifier, enum, coordinate, and timestamp validation.
- [ ] `API-014` Add route tests for success, invalid input, missing resources, active-job conflicts, and unsafe artifact paths.
- [ ] `API-015` Generate a local OpenAPI document and verify schemas contain no SQLite or filesystem implementation types.

## Completion Criteria

- [ ] Every route in the detailed design has a tested application-service boundary.
- [ ] API errors are stable and presentation-ready.
- [ ] Media streaming cannot escape the registered artifact store.

