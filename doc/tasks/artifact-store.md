# Artifact Store Module Tasks

## Goal

Safely manage all local binary artifacts through logical identifiers.

## Dependencies

Filesystem, configuration, artifact metadata repository.

## Checklist

- [x] `ART-001` Define artifact identifier, kind, logical path, metadata, and store port.
- [x] `ART-002` Create configured roots for uploads, run artifacts, temporary files, and models.
- [x] `ART-003` Resolve logical identifiers into normalized paths under allowed roots.
- [x] `ART-004` Reject absolute paths, traversal, symlink escapes, and unknown artifacts.
- [x] `ART-005` Implement temporary file and directory creation scoped to video and run IDs.
- [x] `ART-006` Implement atomic file promotion.
- [x] `ART-007` Implement original, proxy, track, replay, render, and model path policies.
- [x] `ART-008` Implement safe read/stream metadata without exposing physical paths.
- [x] `ART-009` Implement video-owned artifact inventory.
- [x] `ART-010` Implement storage-usage calculation.
- [x] `ART-011` Implement complete video-tree deletion while preserving shared models.
- [x] `ART-012` Add tests for traversal, symlink escape, interrupted writes, duplicate IDs, inventory, usage, and deletion.

## Completion Criteria

- [x] All binary media operations use artifact identifiers.
- [x] Atomic writes prevent partial files from appearing as complete.
- [x] Security tests prove paths cannot escape configured roots.
