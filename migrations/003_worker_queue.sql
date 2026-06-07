CREATE UNIQUE INDEX idx_jobs_run ON analysis_jobs(run_id);

CREATE TABLE worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    stopped_at TEXT
);
CREATE INDEX idx_worker_heartbeats_alive ON worker_heartbeats(stopped_at, heartbeat_at);
