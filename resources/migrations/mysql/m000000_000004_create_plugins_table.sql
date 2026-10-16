CREATE TABLE IF NOT EXISTS plugin_state (
    plugin_name       VARCHAR(255) PRIMARY KEY,
    installed_version VARCHAR(64),
    installed_at      DATETIME,
    updated_at        DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
