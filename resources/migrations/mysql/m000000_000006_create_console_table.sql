CREATE TABLE IF NOT EXISTS console_history (
    id           VARCHAR(36) PRIMARY KEY,
    user_name    VARCHAR(255) NOT NULL,
    command      VARCHAR(255) NOT NULL,
    args_json    TEXT NOT NULL,
    started_at   DATETIME NOT NULL,
    finished_at  DATETIME,
    exit_code    INT,
    output       LONGTEXT,
    input_log    LONGTEXT,
    client_ip    VARCHAR(64),
    user_agent   TEXT,
    duration_ms  INT,
    session_id   VARCHAR(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_history_user
    ON console_history(user_name);

CREATE INDEX idx_history_command
    ON console_history(command);

CREATE INDEX idx_history_started_at
    ON console_history(started_at DESC);
