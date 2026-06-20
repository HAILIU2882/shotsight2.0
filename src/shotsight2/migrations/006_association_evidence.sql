CREATE TABLE association_evidence_references (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    shot_attempt_id TEXT NOT NULL REFERENCES shot_attempts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('possession', 'shooter')),
    player_track_id TEXT REFERENCES player_tracks(id) ON DELETE SET NULL,
    observation_ids_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    ambiguous INTEGER NOT NULL CHECK (ambiguous IN (0, 1)),
    reason TEXT NOT NULL
);
CREATE INDEX idx_association_evidence_attempt
ON association_evidence_references(shot_attempt_id, kind, id);
CREATE INDEX idx_association_evidence_run
ON association_evidence_references(analysis_run_id, kind, id);
