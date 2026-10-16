CREATE TABLE IF NOT EXISTS nodes (
    id           VARCHAR(64) PRIMARY KEY,
    hostname     VARCHAR(255) NOT NULL,
    ip           VARCHAR(64),
    started_at   TIMESTAMP NOT NULL,
    last_seen    TIMESTAMP NOT NULL,
    role         VARCHAR(32) NOT NULL DEFAULT 'worker',
    version      VARCHAR(32),
    meta         TEXT
);

CREATE INDEX IF NOT EXISTS idx_nodes_last_seen
    ON nodes(last_seen);

CREATE TABLE IF NOT EXISTS advisory_locks (
    name        VARCHAR(255) PRIMARY KEY,
    token       VARCHAR(64) NOT NULL,
    locked_at   TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS node_commands (
    id         SERIAL PRIMARY KEY,
    node_id    VARCHAR(64) NOT NULL,
    action     VARCHAR(64) NOT NULL,
    payload    TEXT,
    created_at TIMESTAMP NOT NULL,
    picked_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_node_commands_node
    ON node_commands(node_id, picked_at);

 CREATE TABLE IF NOT EXISTS advisory_locks (
    name        VARCHAR(255) PRIMARY KEY,
    token       VARCHAR(64) NOT NULL,
    locked_at   TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP NOT NULL
);
