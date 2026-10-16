BEGIN
    EXECUTE IMMEDIATE '
        CREATE TABLE plugin_state (
            plugin_name       VARCHAR2(255) PRIMARY KEY,
            installed_version VARCHAR2(64),
            installed_at      TIMESTAMP,
            updated_at        TIMESTAMP
        )';
EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
