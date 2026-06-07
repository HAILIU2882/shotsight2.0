# Persistence Module Tasks

## Goal

Provide transactional SQLite repositories without leaking storage-specific
types into domain or application code.

## Dependencies

Domain models, repository ports, SQLite driver, migration mechanism.

## Checklist

- [ ] `DB-001` Define repository protocols for all families listed in the detailed design.
- [ ] `DB-002` Define SQLite connection, transaction, row-mapping, and timestamp conventions.
- [ ] `DB-003` Create initial migration tables, indexes, constraints, and foreign keys.
- [ ] `DB-004` Implement `VideoRepository`.
- [ ] `DB-005` Implement `AnalysisRunRepository` and `JobRepository`.
- [ ] `DB-006` Implement camera-segment and calibration repositories.
- [ ] `DB-007` Implement player-track and ball-track repositories.
- [ ] `DB-008` Implement shot-attempt, location, and correction repositories.
- [ ] `DB-009` Implement artifact metadata repository.
- [ ] `DB-010` Implement atomic completed-run publication.
- [ ] `DB-011` Implement effective-attempt queries without mutating automatic rows.
- [ ] `DB-012` Enable foreign keys, busy timeout, and safe local concurrency settings.
- [ ] `DB-013` Add migration upgrade tests from an empty database.
- [ ] `DB-014` Add repository contract tests using temporary databases.
- [ ] `DB-015` Add backup/diagnostic metadata without copying video content.

## Completion Criteria

- [ ] Application and domain packages import no SQLite row or connection types.
- [ ] Failed transactions leave no partial published analysis.
- [ ] All repository contract tests pass.

