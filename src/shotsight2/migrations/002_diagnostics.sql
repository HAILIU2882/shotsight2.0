CREATE TABLE database_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO database_metadata(key, value, updated_at)
VALUES ('application', 'ShotSight 2.0', CURRENT_TIMESTAMP);
