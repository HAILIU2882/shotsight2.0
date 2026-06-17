CREATE TABLE tracking_prompts (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES camera_segments(id) ON DELETE CASCADE,
    timestamp_seconds REAL NOT NULL CHECK (timestamp_seconds >= 0),
    object_class TEXT NOT NULL CHECK (object_class IN ('basketball', 'player', 'rim')),
    kind TEXT NOT NULL CHECK (kind IN ('concept', 'point', 'box', 'mask')),
    source TEXT NOT NULL CHECK (source IN ('automatic', 'user')),
    target_track_id TEXT,
    text_value TEXT,
    geometry_json TEXT,
    mask_artifact_id TEXT,
    mask_frame_index INTEGER
);
CREATE INDEX idx_tracking_prompts_segment_time
ON tracking_prompts(segment_id, timestamp_seconds, id);

CREATE TABLE tracking_observations (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL REFERENCES camera_segments(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL CHECK (frame_index >= 0),
    timestamp_seconds REAL NOT NULL CHECK (timestamp_seconds >= 0),
    object_class TEXT NOT NULL CHECK (object_class IN ('basketball', 'player', 'rim')),
    local_track_id TEXT NOT NULL,
    bounding_box_json TEXT NOT NULL,
    centroid_json TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    visibility TEXT NOT NULL CHECK (visibility IN ('visible', 'partial', 'occluded', 'lost')),
    occluded INTEGER NOT NULL CHECK (occluded IN (0, 1)),
    mask_artifact_id TEXT,
    mask_frame_index INTEGER,
    backend_name TEXT NOT NULL,
    backend_version TEXT,
    model TEXT,
    session_id TEXT NOT NULL,
    prompt_id TEXT REFERENCES tracking_prompts(id) ON DELETE SET NULL,
    reinitialized INTEGER NOT NULL CHECK (reinitialized IN (0, 1)),
    UNIQUE (segment_id, frame_index, object_class, local_track_id)
);
CREATE INDEX idx_tracking_observations_segment_time
ON tracking_observations(segment_id, timestamp_seconds, object_class, local_track_id);
