CREATE TABLE IF NOT EXISTS console_history (
    id           VARCHAR(36) PRIMARY KEY,
    user_name    VARCHAR(255) NOT NULL,
    command      VARCHAR(255) NOT NULL,
    args_json    TEXT NOT NULL DEFAULT '{}',
    started_at   TIMESTAMP NOT NULL,
    finished_at  TIMESTAMP,
    exit_code    INTEGER,
    output       TEXT,
    input_log    TEXT,
    client_ip    VARCHAR(64),
    user_agent   TEXT,
    duration_ms  INTEGER,
    session_id   VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_history_user
    ON console_history(user_name);

CREATE INDEX IF NOT EXISTS idx_history_command
    ON console_history(command);

CREATE INDEX IF NOT EXISTS idx_history_started_at
    ON console_history(started_at DESC);
