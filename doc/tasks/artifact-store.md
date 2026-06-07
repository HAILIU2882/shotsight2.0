# Artifact Store Module Tasks

## Goal

Safely manage all local binary artifacts through logical identifiers.

## Dependencies

Filesystem, configuration, artifact metadata repository.

## Checklist

- [ ] `ART-001` Define artifact identifier, kind, logical path, metadata, and store port.
- [ ] `ART-002` Create configured roots for uploads, run artifacts, temporary files, and models.
- [ ] `ART-003` Resolve logical identifiers into normalized paths under allowed roots.
- [ ] `ART-004` Reject absolute paths, traversal, symlink escapes, and unknown artifacts.
- [ ] `ART-005` Implement temporary file and directory creation scoped to video and run IDs.
- [ ] `ART-006` Implement atomic file promotion.
- [ ] `ART-007` Implement original, proxy, track, replay, render, and model path policies.
- [ ] `ART-008` Implement safe read/stream metadata without exposing physical paths.
- [ ] `ART-009` Implement video-owned artifact inventory.
- [ ] `ART-010` Implement storage-usage calculation.
- [ ] `ART-011` Implement complete video-tree deletion while preserving shared models.
- [ ] `ART-012` Add tests for traversal, symlink escape, interrupted writes, duplicate IDs, inventory, usage, and deletion.

## Completion Criteria

- [ ] All binary media operations use artifact identifiers.
- [ ] Atomic writes prevent partial files from appearing as complete.
- [ ] Security tests prove paths cannot escape configured roots.

