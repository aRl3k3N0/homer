BEGIN
    EXECUTE IMMEDIATE '
        CREATE TABLE console_history (
            id           VARCHAR2(36) PRIMARY KEY,
            user_name    VARCHAR2(255) NOT NULL,
            command      VARCHAR2(255) NOT NULL,
            args_json    CLOB DEFAULT ''{}'' NOT NULL,
            started_at   TIMESTAMP NOT NULL,
            finished_at  TIMESTAMP,
            exit_code    NUMBER,
            output       CLOB,
            input_log    CLOB,
            client_ip    VARCHAR2(64),
            user_agent   VARCHAR2(4000),
            duration_ms  NUMBER,
            session_id   VARCHAR2(64)
        )';
EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
