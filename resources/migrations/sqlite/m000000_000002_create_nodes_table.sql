CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    hostname     TEXT NOT NULL,
    ip           TEXT,
    started_at   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    role         TEXT DEFAULT 'worker',
    version      TEXT,
    meta         TEXT
);

CREATE INDEX IF NOT EXISTS idx_nodes_last_seen
    ON nodes(last_seen);

CREATE TABLE IF NOT EXISTS node_commands (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL,
    action     TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL,
    picked_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_node_commands_node
    ON node_commands(node_id, picked_at);

CREATE TABLE IF NOT EXISTS advisory_locks (
    name        TEXT PRIMARY KEY,
    token       TEXT NOT NULL,
    locked_at   TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
