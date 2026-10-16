CREATE TABLE IF NOT EXISTS nodes (
    id           VARCHAR(64) PRIMARY KEY,
    hostname     VARCHAR(255) NOT NULL,
    ip           VARCHAR(64),
    started_at   DATETIME NOT NULL,
    last_seen    DATETIME NOT NULL,
    role         VARCHAR(32) NOT NULL DEFAULT 'worker',
    version      VARCHAR(32),
    meta         TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_nodes_last_seen
    ON nodes(last_seen);

CREATE TABLE IF NOT EXISTS node_commands (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    node_id    VARCHAR(64) NOT NULL,
    action     VARCHAR(64) NOT NULL,
    payload    TEXT,
    created_at DATETIME NOT NULL,
    picked_at  DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_node_commands_node
    ON node_commands(node_id, picked_at);

CREATE TABLE IF NOT EXISTS advisory_locks (
    name        VARCHAR(255) PRIMARY KEY,
    token       VARCHAR(64) NOT NULL,
    locked_at   DATETIME NOT NULL,
    expires_at  DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
