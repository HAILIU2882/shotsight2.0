# Video Library Module Tasks

## Goal

Provide read-only dashboard projections for videos, runs, results, artifacts,
and storage usage.

## Dependencies

Video, analysis-run, shot-attempt, artifact, and job repositories.

## Checklist

- [ ] `LIB-001` Define video-card and video-detail query models.
- [ ] `LIB-002` Implement video listing ordered by most recent activity.
- [ ] `LIB-003` Include latest analysis status, progress, and failure summary.
- [ ] `LIB-004` Include attempts, makes, misses, and shooting percentage when available.
- [ ] `LIB-005` Include artifact availability without exposing physical paths.
- [ ] `LIB-006` Include review-required and low-confidence counts.
- [ ] `LIB-007` Include player and two-point/three-point summary projections.
- [ ] `LIB-008` Calculate per-video and total local storage usage.
- [ ] `LIB-009` Return explicit empty and never-analyzed states.
- [ ] `LIB-010` Add query tests for uploaded, queued, running, failed, completed, and corrected videos.

## Completion Criteria

- [ ] Library queries perform no writes.
- [ ] A single query service supplies all dashboard information.
- [ ] Query tests cover videos with and without completed analyses.

