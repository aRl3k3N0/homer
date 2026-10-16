CREATE TABLE IF NOT EXISTS console_history (
    id           TEXT PRIMARY KEY,
    user_name    TEXT NOT NULL,
    command      TEXT NOT NULL,
    args_json    TEXT NOT NULL DEFAULT '{}',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    exit_code    INTEGER,
    output       TEXT,
    input_log    TEXT,
    client_ip    TEXT,
    user_agent   TEXT,
    duration_ms  INTEGER,
    session_id   TEXT
);

CREATE INDEX IF NOT EXISTS idx_history_user
    ON console_history(user_name);

CREATE INDEX IF NOT EXISTS idx_history_command
    ON console_history(command);

CREATE INDEX IF NOT EXISTS idx_history_started_at
    ON console_history(started_at DESC);
