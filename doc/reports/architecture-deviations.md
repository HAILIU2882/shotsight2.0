# Architecture Deviations

## Windows/Linux Smoke Test Deferral

- **Expected design:** The product proposal asks for macOS, Windows, and Linux
  support.
- **Implemented design:** Current release validation targets native macOS only.
  Windows and Linux remain portable design targets but are not smoke-tested in
  this phase.
- **Reason:** `doc/prompt.md` explicitly scopes current validation to macOS and
  states that Windows/Linux smoke tests must not be falsely marked complete.
- **Affected requirements:** Cross-platform installation and smoke-test release
  gate.
- **Risks:** Platform-specific packaging, shell scripts, FFmpeg availability,
  filesystem behavior, or optional vision backend behavior may still differ on
  Windows/Linux.
- **Migration plan:** Add Windows and Linux CI or manual smoke-test evidence,
  then update `doc/tasks/progress.md` and this report.
