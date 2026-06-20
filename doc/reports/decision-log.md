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

## 2026-06-20 - Separate Web Liveness from Analysis Readiness

- **Affected modules:** Application API, Worker Queue
- **Ambiguity:** A single endpoint cannot simultaneously be a safe web-process
  liveness probe and fail when the independently supervised analysis worker is
  unavailable.
- **Decision:** Keep `/health` HTTP-200 compatible for web liveness and expose
  `/ready` for database, queue, and worker-heartbeat readiness. `/ready` returns
  HTTP 503 unless a non-stopped worker has a heartbeat within the configured
  freshness window. Active records take precedence over newer stopped records.
- **Alternatives:** Make `/health` return HTTP 503 when the worker is absent, or
  always return HTTP 200 with a nested readiness flag.
- **Rationale:** Separate endpoints preserve reliable container/process
  supervision while giving the UI and operations an actionable analysis gate.
- **Reversal:** The routes can be versioned later if deployment orchestration
  adopts a different probe contract.
