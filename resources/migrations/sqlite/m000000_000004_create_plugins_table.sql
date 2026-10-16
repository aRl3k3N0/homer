CREATE TABLE IF NOT EXISTS plugins_state (
    plugin_name       TEXT PRIMARY KEY,
    installed_version TEXT,
    installed_at      TEXT,
    updated_at        TEXT
);
