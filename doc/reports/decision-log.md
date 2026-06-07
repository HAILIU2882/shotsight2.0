# Decision Log

## 2026-06-07 - Foundation Wave File Ownership

- **Affected modules:** Persistence, Artifact Store, Media Processing, Tracking
  Backend Selection
- **Ambiguity:** The detailed design defines clean ports, but the empty scaffold
  does not yet assign ownership of shared port files.
- **Decision:** Each first-wave module owns only its matching port and adapter
  subtree. Persistence owns baseline test-import configuration and formatting
  because it establishes the first shared infrastructure baseline.
- **Alternatives:** Run the modules sequentially or create a separate foundation
  module not present in the approved 22-module plan.
- **Rationale:** Disjoint ownership permits approved parallel work without
  inventing a twenty-third implementation module.
- **Reversal:** Shared ports can be reorganized later through an explicitly
  reviewed architecture change.

## 2026-06-07 - Baseline Editable Import Failure

- **Affected module:** Persistence
- **Ambiguity:** The generated editable-install `.pth` exists but the local
  Python environment does not add the source directory to `sys.path`.
- **Decision:** Persistence will make test package discovery explicit in project
  configuration instead of relying on environment-specific editable behavior.
- **Alternatives:** Set `PYTHONPATH` manually for every command or modify the
  generated virtual environment.
- **Rationale:** Project-level configuration is portable, reproducible, and
  version controlled.
- **Reversal:** Remove the explicit setting after all supported packaging
  environments prove reliable editable installation behavior.
