# Deletion Module Tasks

## Goal

Completely and safely remove a video and all owned records and artifacts after
explicit confirmation.

## Dependencies

All video-owned repositories, artifact store, job repository.

## Checklist

- [ ] `DEL-001` Define deletion inventory and deletion-result models.
- [ ] `DEL-002` Build a pre-deletion inventory of records, artifacts, and total bytes.
- [ ] `DEL-003` Reject deletion when the video has an active analysis job.
- [ ] `DEL-004` Mark the video as deleting before filesystem changes begin.
- [ ] `DEL-005` Delete the video-owned artifact tree while preserving shared model files.
- [ ] `DEL-006` Delete corrections, locations, attempts, tracks, calibrations, segments, runs, jobs, artifacts, and video metadata in safe order.
- [ ] `DEL-007` Define partial-cleanup state when filesystem deletion fails.
- [ ] `DEL-008` Allow retry of incomplete cleanup.
- [ ] `DEL-009` Make repeated deletion requests idempotent.
- [ ] `DEL-010` Add audit logging without retaining deleted media paths unnecessarily.
- [ ] `DEL-011` Add tests for complete deletion, active-job conflict, missing files, locked files, partial failure, retry, and unrelated-video preservation.

## Completion Criteria

- [ ] Successful deletion leaves no video-owned database record or artifact.
- [ ] Partial failure is visible and recoverable.
- [ ] Other videos and shared models remain unchanged.

