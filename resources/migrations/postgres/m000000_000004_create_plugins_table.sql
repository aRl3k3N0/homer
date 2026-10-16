CREATE TABLE IF NOT EXISTS plugin_state (
    plugin_name       VARCHAR(255) PRIMARY KEY,
    installed_version VARCHAR(64),
    installed_at      TIMESTAMP,
    updated_at        TIMESTAMP
);
