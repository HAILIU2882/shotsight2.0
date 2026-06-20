PRAGMA foreign_keys = ON;

CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    original_artifact_id TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    fps REAL NOT NULL CHECK (fps > 0),
    codec TEXT NOT NULL,
    container TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('READY', 'DELETING', 'CLEANUP_INCOMPLETE')),
    created_at TEXT NOT NULL
);

CREATE TABLE analysis_runs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    backend_name TEXT NOT NULL,
    backend_version TEXT NOT NULL,
    configuration_json TEXT NOT NULL,
    progress REAL NOT NULL CHECK (progress >= 0 AND progress <= 1),
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_json TEXT,
    published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1))
);
CREATE INDEX idx_analysis_runs_video ON analysis_runs(video_id, started_at DESC);
CREATE UNIQUE INDEX idx_one_published_run_per_video ON analysis_runs(video_id) WHERE published = 1;

CREATE TABLE analysis_jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    stage TEXT NOT NULL,
    progress REAL NOT NULL CHECK (progress >= 0 AND progress <= 1),
    error_json TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobs_status_created ON analysis_jobs(status, created_at);
CREATE INDEX idx_jobs_video ON analysis_jobs(video_id, created_at DESC);

CREATE TABLE camera_segments (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
    end_seconds REAL NOT NULL CHECK (end_seconds > start_seconds),
    stability_status TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    representative_artifact_id TEXT
);
CREATE INDEX idx_segments_run_time ON camera_segments(analysis_run_id, start_seconds);

CREATE TABLE calibrations (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES camera_segments(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    rim_geometry_json TEXT NOT NULL,
    court_points_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    indicative_only INTEGER NOT NULL CHECK (indicative_only IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_calibrations_segment_created ON calibrations(segment_id, created_at);

CREATE TABLE player_tracks (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    local_label TEXT NOT NULL,
    display_name TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    observations_artifact_id TEXT,
    UNIQUE (analysis_run_id, local_label)
);
CREATE INDEX idx_player_tracks_video ON player_tracks(video_id);

CREATE TABLE ball_tracks (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES camera_segments(id) ON DELETE CASCADE,
    observations_artifact_id TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    coverage REAL NOT NULL CHECK (coverage >= 0 AND coverage <= 1),
    identity_switches INTEGER NOT NULL CHECK (identity_switches >= 0)
);
CREATE INDEX idx_ball_tracks_segment ON ball_tracks(segment_id);

CREATE TABLE shot_attempts (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    shooter_track_id TEXT REFERENCES player_tracks(id) ON DELETE SET NULL,
    release_seconds REAL NOT NULL CHECK (release_seconds >= 0),
    automatic_outcome TEXT NOT NULL CHECK (automatic_outcome IN ('MADE', 'MISSED', 'UNCERTAIN')),
    shot_type TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    review_status TEXT NOT NULL CHECK (review_status IN ('UNREVIEWED', 'REVIEWED')),
    evidence_json TEXT NOT NULL,
    manual INTEGER NOT NULL DEFAULT 0 CHECK (manual IN (0, 1))
);
CREATE INDEX idx_attempts_run_release ON shot_attempts(analysis_run_id, release_seconds);

CREATE TABLE shot_locations (
    id TEXT PRIMARY KEY,
    shot_attempt_id TEXT NOT NULL UNIQUE REFERENCES shot_attempts(id) ON DELETE CASCADE,
    court_x_m REAL,
    court_y_m REAL,
    normalized_x REAL NOT NULL,
    normalized_y REAL NOT NULL,
    region TEXT NOT NULL,
    indicative INTEGER NOT NULL CHECK (indicative IN (0, 1))
);

CREATE TABLE review_corrections (
    id TEXT PRIMARY KEY,
    shot_attempt_id TEXT NOT NULL REFERENCES shot_attempts(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    previous_value_json TEXT NOT NULL,
    corrected_value_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_corrections_attempt_field ON review_corrections(shot_attempt_id, field, created_at, id);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    analysis_run_id TEXT REFERENCES analysis_runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    logical_path TEXT NOT NULL UNIQUE,
    version TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_artifacts_video ON artifacts(video_id);
CREATE INDEX idx_artifacts_run ON artifacts(analysis_run_id);
