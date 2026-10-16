CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    command      TEXT NOT NULL,
    args         TEXT NOT NULL DEFAULT '{}',
    cron         TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    description  TEXT DEFAULT '',
    last_run     TEXT,
    last_status  TEXT,
    last_error   TEXT,
    next_run     TEXT,
    locked_by    TEXT,
    lease_until  TEXT,
    run_id       TEXT,
    heartbeat_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_enabled ON tasks(enabled);
CREATE INDEX IF NOT EXISTS idx_tasks_lease   ON tasks(lease_until);
