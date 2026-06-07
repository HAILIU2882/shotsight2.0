# Persistence Module Tasks

## Goal

Provide transactional SQLite repositories without leaking storage-specific
types into domain or application code.

## Dependencies

Domain models, repository ports, SQLite driver, migration mechanism.

## Checklist

- [x] `DB-001` Define repository protocols for all families listed in the detailed design.
- [x] `DB-002` Define SQLite connection, transaction, row-mapping, and timestamp conventions.
- [x] `DB-003` Create initial migration tables, indexes, constraints, and foreign keys.
- [x] `DB-004` Implement `VideoRepository`.
- [x] `DB-005` Implement `AnalysisRunRepository` and `JobRepository`.
- [x] `DB-006` Implement camera-segment and calibration repositories.
- [x] `DB-007` Implement player-track and ball-track repositories.
- [x] `DB-008` Implement shot-attempt, location, and correction repositories.
- [x] `DB-009` Implement artifact metadata repository.
- [x] `DB-010` Implement atomic completed-run publication.
- [x] `DB-011` Implement effective-attempt queries without mutating automatic rows.
- [x] `DB-012` Enable foreign keys, busy timeout, and safe local concurrency settings.
- [x] `DB-013` Add migration upgrade tests from an empty database.
- [x] `DB-014` Add repository contract tests using temporary databases.
- [x] `DB-015` Add backup/diagnostic metadata without copying video content.

## Completion Criteria

- [x] Application and domain packages import no SQLite row or connection types.
- [x] Failed transactions leave no partial published analysis.
- [x] All repository contract tests pass.
