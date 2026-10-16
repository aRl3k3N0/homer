CREATE TABLE IF NOT EXISTS tasks (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL UNIQUE,
    command      VARCHAR(255) NOT NULL,
    args         TEXT NOT NULL DEFAULT '{}',
    cron         VARCHAR(128) NOT NULL,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    description  TEXT DEFAULT '',
    last_run     TIMESTAMP,
    last_status  VARCHAR(32),
    last_error   TEXT,
    next_run     TIMESTAMP,
    locked_by    VARCHAR(255),
    lease_until  TIMESTAMP,
    run_id       VARCHAR(64),
    heartbeat_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_enabled ON tasks(enabled);
CREATE INDEX IF NOT EXISTS idx_tasks_lease   ON tasks(lease_until);
