DROP TABLE IF EXISTS migrations;

CREATE TABLE migrations (
    version     VARCHAR(255) NOT NULL,
    source      VARCHAR(255) NOT NULL,
    apply_time  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    checksum    VARCHAR(64),
    PRIMARY KEY (version, source),
    KEY idx_migrations_apply_time (apply_time DESC),
    KEY idx_migrations_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CONSTRAINT chk_migrations_source CHECK (
    source IN ('system', 'project')
    OR source LIKE 'plugin:%'
);
