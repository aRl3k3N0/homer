CREATE TABLE IF NOT EXISTS editor_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    user_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    target       TEXT NOT NULL,
    action       TEXT NOT NULL,
    before       TEXT,
    after        TEXT,
    checksum     TEXT,
    source       TEXT
);

CREATE INDEX IF NOT EXISTS idx_editor_history_target
    ON editor_history(category, target, ts DESC);

CREATE TABLE IF NOT EXISTS editor_locks (
    resource   TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    token      TEXT NOT NULL,
    locked_at  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    client_ip  TEXT
);

CREATE INDEX IF NOT EXISTS idx_editor_locks_expires
    ON editor_locks(expires_at);
