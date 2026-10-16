DROP TABLE IF EXISTS migrations;

CREATE TABLE migrations (
    version     TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    apply_time  TEXT    NOT NULL,
    checksum    TEXT,
    PRIMARY KEY (version, source)
);
