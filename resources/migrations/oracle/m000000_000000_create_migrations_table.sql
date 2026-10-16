DROP TABLE IF EXISTS migrations;

CREATE TABLE migrations (
    version     VARCHAR2(255 CHAR) NOT NULL,
    source      VARCHAR2(255 CHAR) NOT NULL,
    apply_time  TIMESTAMP(6) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    checksum    VARCHAR2(64),
    CONSTRAINT pk_migrations PRIMARY KEY (version, source)
);

CONSTRAINT chk_migrations_source CHECK (
    source IN ('system', 'project')
    OR source LIKE 'plugin:%'
);

CREATE INDEX idx_migrations_apply_time
    ON migrations (apply_time DESC);

CREATE INDEX idx_migrations_source
    ON migrations (source);
