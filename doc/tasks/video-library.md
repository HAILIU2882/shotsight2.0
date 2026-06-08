# Video Library Module Tasks

## Goal

Provide read-only dashboard projections for videos, runs, results, artifacts,
and storage usage.

## Dependencies

Video, analysis-run, shot-attempt, artifact, and job repositories.

## Checklist

- [x] `LIB-001` Define video-card and video-detail query models.
- [x] `LIB-002` Implement video listing ordered by most recent activity.
- [x] `LIB-003` Include latest analysis status, progress, and failure summary.
- [x] `LIB-004` Include attempts, makes, misses, and shooting percentage when available.
- [x] `LIB-005` Include artifact availability without exposing physical paths.
- [x] `LIB-006` Include review-required and low-confidence counts.
- [x] `LIB-007` Include player and two-point/three-point summary projections.
- [x] `LIB-008` Calculate per-video and total local storage usage.
- [x] `LIB-009` Return explicit empty and never-analyzed states.
- [x] `LIB-010` Add query tests for uploaded, queued, running, failed, completed, and corrected videos.

## Completion Criteria

- [x] Library queries perform no writes.
- [x] A single query service supplies all dashboard information.
- [x] Query tests cover videos with and without completed analyses.
