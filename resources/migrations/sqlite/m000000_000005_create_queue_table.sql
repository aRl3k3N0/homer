CREATE TABLE IF NOT EXISTS queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    command          TEXT NOT NULL,
    args             TEXT NOT NULL DEFAULT '{}',
    priority         INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending',
    result           TEXT,
    exit_code        INTEGER,
    error            TEXT,
    created_at       TEXT NOT NULL,
    run_at           TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    parent_job_id    INTEGER,
    locked_by        TEXT,
    lease_until      TEXT,
    run_id           TEXT,
    triggered_by     TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    retry_delay      INTEGER NOT NULL DEFAULT 60,
    last_attempt_at  TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    timeout_sec      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_queue_status   ON queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_priority ON queue(priority DESC, id ASC);
CREATE INDEX IF NOT EXISTS idx_queue_run_at   ON queue(run_at);
CREATE INDEX IF NOT EXISTS idx_queue_parent   ON queue(parent_job_id);
