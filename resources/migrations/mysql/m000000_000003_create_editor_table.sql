CREATE TABLE IF NOT EXISTS editor_history (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    ts           DATETIME NOT NULL,
    user_name    VARCHAR(255) NOT NULL,
    category     VARCHAR(32) NOT NULL,
    target       VARCHAR(512) NOT NULL,
    action       VARCHAR(32) NOT NULL,
    `before`       LONGTEXT,
    after        LONGTEXT,
    checksum     VARCHAR(64),
    source       VARCHAR(512)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_editor_history_target
    ON editor_history(category, target, ts DESC);

CREATE TABLE IF NOT EXISTS editor_locks (
    resource   VARCHAR(512) PRIMARY KEY,
    owner      VARCHAR(255) NOT NULL,
    token      VARCHAR(64) NOT NULL,
    locked_at  DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    client_ip  VARCHAR(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_editor_locks_expires ON editor_locks(expires_at);
