# Deletion Module Tasks

## Goal

Completely and safely remove a video and all owned records and artifacts after
explicit confirmation.

## Dependencies

All video-owned repositories, artifact store, job repository.

## Checklist

- [x] `DEL-001` Define deletion inventory and deletion-result models.
- [x] `DEL-002` Build a pre-deletion inventory of records, artifacts, and total bytes.
- [x] `DEL-003` Reject deletion when the video has an active analysis job.
- [x] `DEL-004` Mark the video as deleting before filesystem changes begin.
- [x] `DEL-005` Delete the video-owned artifact tree while preserving shared model files.
- [x] `DEL-006` Delete corrections, locations, attempts, tracks, calibrations, segments, runs, jobs, artifacts, and video metadata in safe order.
- [x] `DEL-007` Define partial-cleanup state when filesystem deletion fails.
- [x] `DEL-008` Allow retry of incomplete cleanup.
- [x] `DEL-009` Make repeated deletion requests idempotent.
- [x] `DEL-010` Add audit logging without retaining deleted media paths unnecessarily.
- [x] `DEL-011` Add tests for complete deletion, active-job conflict, missing files, locked files, partial failure, retry, and unrelated-video preservation.

## Completion Criteria

- [x] Successful deletion leaves no video-owned database record or artifact.
- [x] Partial failure is visible and recoverable.
- [x] Other videos and shared models remain unchanged.
