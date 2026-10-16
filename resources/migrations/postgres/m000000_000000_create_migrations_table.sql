DROP TABLE IF EXISTS migrations;

CREATE TABLE migrations (
    version     TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    apply_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum    VARCHAR(64),
    CONSTRAINT pk_migrations PRIMARY KEY (version, source)
);

CONSTRAINT chk_migrations_source CHECK (
    source IN ('system', 'project')
    OR source ~ '^plugin:[a-zA-Z0-9_.-]+$'
);

CREATE INDEX IF NOT EXISTS idx_migrations_apply_time
    ON migrations (apply_time DESC);

CREATE INDEX IF NOT EXISTS idx_migrations_source
    ON migrations (source);
