CREATE TABLE IF NOT EXISTS queue (
    id               SERIAL PRIMARY KEY,
    command          VARCHAR(255) NOT NULL,
    args             TEXT NOT NULL DEFAULT '{}',
    priority         INTEGER NOT NULL DEFAULT 0,
    status           VARCHAR(32) NOT NULL DEFAULT 'pending',
    result           TEXT,
    exit_code        INTEGER,
    error            TEXT,
    created_at       TIMESTAMP NOT NULL,
    run_at           TIMESTAMP,
    started_at       TIMESTAMP,
    finished_at      TIMESTAMP,
    parent_job_id    INTEGER,
    locked_by        VARCHAR(255),
    lease_until      TIMESTAMP,
    run_id           VARCHAR(64),
    triggered_by     VARCHAR(255),
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    retry_delay      INTEGER NOT NULL DEFAULT 60,
    last_attempt_at  TIMESTAMP,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    timeout_sec      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_queue_status   ON queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_priority ON queue(priority DESC, id ASC);
CREATE INDEX IF NOT EXISTS idx_queue_run_at   ON queue(run_at);
CREATE INDEX IF NOT EXISTS idx_queue_parent   ON queue(parent_job_id);
