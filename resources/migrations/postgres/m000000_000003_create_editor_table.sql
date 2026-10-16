CREATE TABLE IF NOT EXISTS editor_history (
    id           SERIAL PRIMARY KEY,
    ts           TIMESTAMP NOT NULL,
    user_name    VARCHAR(255) NOT NULL,
    category     VARCHAR(32) NOT NULL,
    target       VARCHAR(512) NOT NULL,
    action       VARCHAR(32) NOT NULL,
    before       TEXT,
    after        TEXT,
    checksum     VARCHAR(64),
    source       VARCHAR(512)
);

CREATE INDEX IF NOT EXISTS idx_editor_history_target
    ON editor_history(category, target, ts DESC);

CREATE TABLE IF NOT EXISTS editor_locks (
    resource   VARCHAR(512) PRIMARY KEY,
    owner      VARCHAR(255) NOT NULL,
    token      VARCHAR(64) NOT NULL,
    locked_at  TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    client_ip  VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_editor_locks_expires
    ON editor_locks(expires_at);
