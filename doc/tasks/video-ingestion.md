# Video Ingestion Module Tasks

## Goal

Safely accept, validate, preserve, and register local source videos.

## Dependencies

Media tool port, video repository, artifact store, configuration.

## Checklist

- [ ] `ING-001` Define upload command, result, and ingestion error types.
- [ ] `ING-002` Stream an upload into a generated temporary path without loading the whole file into memory.
- [ ] `ING-003` Stop and reject uploads exceeding 1 GB.
- [ ] `ING-004` Probe the temporary file through the media tool.
- [ ] `ING-005` Reject files longer than 30 minutes.
- [ ] `ING-006` Reject files that FFmpeg cannot decode and retain the diagnostic reason.
- [ ] `ING-007` Record container, codecs, duration, dimensions, frame rate, orientation, and size.
- [ ] `ING-008` Generate storage-safe identifiers independently of the user filename.
- [ ] `ING-009` Atomically promote the validated temporary file to permanent original storage.
- [ ] `ING-010` Persist the `Video` in `READY` state after the original is durable.
- [ ] `ING-011` Remove temporary files after every rejection or unexpected error.
- [ ] `ING-012` Add tests for valid media, corrupt files, unsupported codecs, duration limit, size limit, interrupted streams, and duplicate filenames.

## Completion Criteria

- [ ] Original media is preserved byte-for-byte after successful upload.
- [ ] Invalid uploads leave no database row or orphan temporary file.
- [ ] No upload path is derived directly from an untrusted filename.

