CREATE TABLE IF NOT EXISTS notes_data (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS notes_data_created_idx
    ON notes_data (created_at DESC);
