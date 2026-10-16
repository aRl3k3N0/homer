-- =====================================================================
-- HOMER — Distributed Infrastructure Management System
-- Полный DDL базы данных.
--
-- Порядок применения:
--   1. Расширения и схемы
--   2. core (пользователи, роли, пространства, master nodes)
--   3. framework (миграции, кэш)
--   4. audit (аудит)
--   5. cluster (ноды, heartbeat)
--   6. inventory (серверы)
--   7. automation (команды, playbook, шаблоны)
--   8. tasks (задачи)
--   9. scheduling (расписания)
--  10. drift (дрейф)
--  11. locks (блокировки ресурсов)
--  12. sync (синхронизация файлов)
--  13. auth (OAuth)
--  14. monitoring (метрики, алерты)
--  15. reporting (views)
--  16. Seed: базовые роли, права, пространство default
--
-- ВАЖНО: этот файл идемпотентен по схемам, но НЕ по таблицам.
-- Для чистой установки. Для обновления — миграции в migrations/system/.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. Расширения
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;     -- регистронезависимые строки
-- CREATE EXTENSION IF NOT EXISTS timescaledb;  -- опционально, для metrics

-- ---------------------------------------------------------------------
-- 1. Схемы
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS core;          -- пользователи, роли, пространства
CREATE SCHEMA IF NOT EXISTS framework;     -- миграции, кэш
CREATE SCHEMA IF NOT EXISTS audit;         -- аудит
CREATE SCHEMA IF NOT EXISTS cluster;       -- ноды кластера, heartbeat
CREATE SCHEMA IF NOT EXISTS inventory;     -- серверы
CREATE SCHEMA IF NOT EXISTS automation;    -- команды, playbook, шаблоны
CREATE SCHEMA IF NOT EXISTS tasks;         -- задачи
CREATE SCHEMA IF NOT EXISTS scheduling;    -- расписания
CREATE SCHEMA IF NOT EXISTS drift;         -- дрейф конфигов
CREATE SCHEMA IF NOT EXISTS locks;         -- блокировки ресурсов
CREATE SCHEMA IF NOT EXISTS sync;          -- синхронизация файлов
CREATE SCHEMA IF NOT EXISTS auth;          -- OAuth
CREATE SCHEMA IF NOT EXISTS monitoring;    -- метрики, алерты
CREATE SCHEMA IF NOT EXISTS reporting;     -- views для UI

-- public не используем для прикладных данных. Только для расширений.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------
-- 2. CORE
-- ---------------------------------------------------------------------

-- 2.1. Источники идентификации
CREATE TABLE core.user_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            CITEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL,                  -- 'local' | 'ad' | 'ldap' | 'oidc'
    display_name    TEXT NOT NULL,
    description     TEXT,
    priority        INT NOT NULL DEFAULT 100,
    managed_attributes TEXT[] NOT NULL DEFAULT '{}',
    connection      JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    sync_interval_seconds INT,
    last_sync_at    TIMESTAMPTZ,
    last_sync_status TEXT,
    last_sync_error TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2.2. Пользователи
CREATE TABLE core.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        CITEXT NOT NULL UNIQUE,
    primary_source_id UUID NOT NULL REFERENCES core.user_sources(id),
    display_name    TEXT,
    email           CITEXT,
    phone           TEXT,
    department      TEXT,
    job_title       TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked       BOOLEAN NOT NULL DEFAULT FALSE,
    lock_reason     TEXT,
    locked_until    TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    last_login_ip   INET,
    login_count     BIGINT NOT NULL DEFAULT 0,
    failed_login_count INT NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT chk_users_username_no_domain CHECK (username !~ '@')
);
CREATE INDEX idx_users_primary_source ON core.users(primary_source_id);
CREATE INDEX idx_users_email ON core.users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_active ON core.users(is_active) WHERE deleted_at IS NULL;

-- 2.3. Идентичности
CREATE TABLE core.user_identities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    source_id       UUID NOT NULL REFERENCES core.user_sources(id),
    external_id     TEXT NOT NULL,
    external_username TEXT,
    attributes      JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at  TIMESTAMPTZ,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_id),
    UNIQUE (user_id, source_id)
);
CREATE INDEX idx_user_identities_user ON core.user_identities(user_id);
CREATE INDEX idx_user_identities_external ON core.user_identities(source_id, external_id);
CREATE UNIQUE INDEX idx_user_identities_primary
    ON core.user_identities(user_id) WHERE is_primary;

-- 2.4. Роли и права
CREATE TABLE core.roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        CITEXT NOT NULL UNIQUE,
    description TEXT,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.permissions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        CITEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.role_permissions (
    role_id       UUID NOT NULL REFERENCES core.roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES core.permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE core.user_roles (
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    role_id     UUID NOT NULL REFERENCES core.roles(id) ON DELETE CASCADE,
    granted_by  UUID REFERENCES core.users(id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX idx_user_roles_expires ON core.user_roles(expires_at)
    WHERE expires_at IS NOT NULL;

-- 2.5. Группы AD → роли
CREATE TABLE core.group_role_map (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES core.user_sources(id) ON DELETE CASCADE,
    group_external_id TEXT NOT NULL,
    group_display_name TEXT,
    role_id         UUID NOT NULL REFERENCES core.roles(id) ON DELETE CASCADE,
    effect          TEXT NOT NULL DEFAULT 'allow',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, group_external_id, role_id)
);
CREATE INDEX idx_group_role_map_source ON core.group_role_map(source_id);
CREATE INDEX idx_group_role_map_role ON core.group_role_map(role_id);

-- 2.6. Кэш членства в AD-группах
CREATE TABLE core.user_group_membership (
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    source_id       UUID NOT NULL REFERENCES core.user_sources(id) ON DELETE CASCADE,
    group_external_id TEXT NOT NULL,
    group_display_name TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, source_id, group_external_id)
);
CREATE INDEX idx_user_group_membership_group
    ON core.user_group_membership(source_id, group_external_id);

-- 2.7. Пространства
CREATE TABLE core.spaces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            CITEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    owner_group     TEXT,
    settings        JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

-- 2.8. Master nodes (управляющие серверы)
CREATE TABLE core.master_nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname        TEXT NOT NULL UNIQUE,
    ip_address      INET,
    description     TEXT,
    role            TEXT NOT NULL DEFAULT 'primary',  -- 'primary' | 'replica'
    primary_node_id UUID REFERENCES core.master_nodes(id),
    status          TEXT NOT NULL DEFAULT 'unknown',
    last_heartbeat_at TIMESTAMPTZ,
    capacity        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2.9. Привязка мастер-нод к пространствам
CREATE TABLE core.space_master_nodes (
    space_id        UUID NOT NULL REFERENCES core.spaces(id) ON DELETE CASCADE,
    master_node_id  UUID NOT NULL REFERENCES core.master_nodes(id) ON DELETE CASCADE,
    base_path       TEXT NOT NULL,
    os_user         TEXT NOT NULL,
    os_exec_user    TEXT,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    last_sync_at    TIMESTAMPTZ,
    last_sync_status TEXT,
    last_sync_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (space_id, master_node_id)
);
CREATE INDEX idx_space_master_nodes_space ON core.space_master_nodes(space_id);
CREATE INDEX idx_space_master_nodes_node ON core.space_master_nodes(master_node_id);
CREATE UNIQUE INDEX idx_space_master_nodes_primary
    ON core.space_master_nodes(space_id) WHERE is_primary;

-- 2.10. Члены пространства с ролями
CREATE TABLE core.space_members (
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    space_id        UUID NOT NULL REFERENCES core.spaces(id) ON DELETE CASCADE,
    role_id         UUID NOT NULL REFERENCES core.roles(id),
    granted_by      UUID REFERENCES core.users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    constraints     JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (user_id, space_id)
);
CREATE INDEX idx_space_members_space ON core.space_members(space_id);
CREATE INDEX idx_space_members_expires ON core.space_members(expires_at)
    WHERE expires_at IS NOT NULL;

-- 2.11. AD-группы → пространства
CREATE TABLE core.space_group_map (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL REFERENCES core.spaces(id) ON DELETE CASCADE,
    source_id       UUID NOT NULL REFERENCES core.user_sources(id),
    group_external_id TEXT NOT NULL,
    group_display_name TEXT,
    role_id         UUID NOT NULL REFERENCES core.roles(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (space_id, source_id, group_external_id)
);

-- 2.12. Сессии
CREATE TABLE core.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    source_id       UUID REFERENCES core.user_sources(id),
    auth_method     TEXT NOT NULL,
    client_id       UUID,
    ip_address      INET,
    user_agent      TEXT,
    session_token_hash TEXT NOT NULL UNIQUE,
    csrf_token_hash    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT
);
CREATE INDEX idx_sessions_user ON core.sessions(user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_sessions_expires ON core.sessions(expires_at) WHERE revoked_at IS NULL;

-- 2.13. Функция эффективных прав в пространстве
CREATE OR REPLACE FUNCTION core.effective_permissions(
    p_user_id   UUID,
    p_space_id  UUID
)
RETURNS TABLE (permission_code TEXT, source TEXT)
LANGUAGE sql STABLE
SET search_path = core
AS $$
    WITH user_roles_global AS (
        SELECT r.id AS role_id, 'user_roles'::text AS source
          FROM core.user_roles ur
          JOIN core.roles r ON r.id = ur.role_id
         WHERE ur.user_id = p_user_id
           AND (ur.expires_at IS NULL OR ur.expires_at > now())
        UNION
        SELECT grm.role_id, 'ad_group'::text
          FROM core.user_group_membership ugm
          JOIN core.group_role_map grm
            ON grm.source_id = ugm.source_id
           AND grm.group_external_id = ugm.group_external_id
           AND grm.effect = 'allow'
         WHERE ugm.user_id = p_user_id
    ),
    user_roles_space AS (
        SELECT sm.role_id, 'space_member'::text AS source
          FROM core.space_members sm
         WHERE sm.user_id = p_user_id
           AND sm.space_id = p_space_id
           AND (sm.expires_at IS NULL OR sm.expires_at > now())
        UNION
        SELECT sgm.role_id, 'space_ad_group'::text
          FROM core.user_group_membership ugm
          JOIN core.space_group_map sgm
            ON sgm.source_id = ugm.source_id
           AND sgm.group_external_id = ugm.group_external_id
           AND sgm.space_id = p_space_id
         WHERE ugm.user_id = p_user_id
    ),
    all_roles AS (
        SELECT * FROM user_roles_global
        UNION ALL
        SELECT * FROM user_roles_space
    )
    SELECT DISTINCT p.code::text, ar.source
      FROM all_roles ar
      JOIN core.role_permissions rp ON rp.role_id = ar.role_id
      JOIN core.permissions p ON p.id = rp.permission_id;
$$;

-- ---------------------------------------------------------------------
-- 3. FRAMEWORK: миграции и кэш
-- ---------------------------------------------------------------------
CREATE TABLE framework.schema_migrations (
    id              BIGSERIAL PRIMARY KEY,
    chain           TEXT NOT NULL,
    version         BIGINT NOT NULL,
    filename        TEXT NOT NULL,
    checksum        TEXT NOT NULL,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by      TEXT NOT NULL,
    duration_ms     INT,
    UNIQUE (chain, version)
);
CREATE INDEX idx_schema_migrations_chain ON framework.schema_migrations(chain, version);

CREATE TABLE framework.cache (
    key             TEXT PRIMARY KEY,
    value           BYTEA NOT NULL,
    value_type      TEXT NOT NULL DEFAULT 'json',  -- 'json' | 'msgpack' | 'pickle'
    namespace       TEXT NOT NULL DEFAULT 'default',
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cache_expires ON framework.cache(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX idx_cache_namespace ON framework.cache(namespace);

CREATE TABLE framework.cache_lock (
    key             TEXT PRIMARY KEY,
    locked_by       TEXT NOT NULL,
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    purpose         TEXT
);
CREATE INDEX idx_cache_lock_expires ON framework.cache_lock(expires_at);

-- ---------------------------------------------------------------------
-- 4. AUDIT
-- ---------------------------------------------------------------------
CREATE TABLE audit.events (
    id              BIGSERIAL,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         UUID,
    client_id       UUID,
    session_id      UUID,
    action          TEXT NOT NULL,
    resource_type   TEXT,
    resource_id     TEXT,
    result          TEXT NOT NULL DEFAULT 'success',
    ip_address      INET,
    user_agent      TEXT,
    request_id      TEXT,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE audit.events_2026_10 PARTITION OF audit.events
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE audit.events_2026_11 PARTITION OF audit.events    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE audit.events_2026_12 PARTITION OF audit.events
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');

CREATE INDEX idx_audit_user_ts ON audit.events(user_id, ts DESC);
CREATE INDEX idx_audit_action_ts ON audit.events(action, ts DESC);
CREATE INDEX idx_audit_resource ON audit.events(resource_type, resource_id, ts DESC);

CREATE OR REPLACE FUNCTION audit.log_event(
    p_action        TEXT,
    p_resource_type TEXT DEFAULT NULL,
    p_resource_id   TEXT DEFAULT NULL,
    p_result        TEXT DEFAULT 'success',
    p_details       JSONB DEFAULT '{}'::jsonb,
    p_user_id       UUID DEFAULT NULL,
    p_client_id     UUID DEFAULT NULL,
    p_session_id    UUID DEFAULT NULL,
    p_ip_address    INET DEFAULT NULL,
    p_user_agent    TEXT DEFAULT NULL,
    p_request_id    TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = audit
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    INSERT INTO audit.events (
        action, resource_type, resource_id, result, details,
        user_id, client_id, session_id,
        ip_address, user_agent, request_id
    ) VALUES (
        p_action, p_resource_type, p_resource_id, p_result, p_details,
        p_user_id, p_client_id, p_session_id,
        p_ip_address, p_user_agent, p_request_id
    ) RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;

-- Append-only
CREATE OR REPLACE FUNCTION audit.prevent_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only';
END;
$$;

CREATE TRIGGER trg_audit_no_update
    BEFORE UPDATE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_modification();
CREATE TRIGGER trg_audit_no_delete
    BEFORE DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_modification();

-- ---------------------------------------------------------------------
-- 5. CLUSTER: ноды, heartbeat, роли
-- ---------------------------------------------------------------------
CREATE TABLE cluster.nodes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_name       TEXT NOT NULL,
    node_kind       TEXT NOT NULL,
    master_node_id  UUID REFERENCES core.master_nodes(id) ON DELETE SET NULL,
    hostname        TEXT NOT NULL,
    ip_address      INET,
    pid             INT,
    runtime         TEXT NOT NULL DEFAULT 'systemd',
    container_id    TEXT,
    image_version   TEXT,
    role            TEXT NOT NULL DEFAULT 'worker',
    worker_group    TEXT,
    status          TEXT NOT NULL DEFAULT 'starting',
    status_reason   TEXT,
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_interval_seconds INT NOT NULL DEFAULT 30,
    desired_state   TEXT NOT NULL DEFAULT 'running',
    accepts_new_tasks BOOLEAN NOT NULL DEFAULT TRUE,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_name, hostname, pid)
);
CREATE INDEX idx_nodes_kind_status ON cluster.nodes(node_kind, status);
CREATE INDEX idx_nodes_master ON cluster.nodes(master_node_id);
CREATE INDEX idx_nodes_heartbeat ON cluster.nodes(last_heartbeat_at)
    WHERE status IN ('online', 'draining');

CREATE TABLE cluster.node_heartbeats (
    node_id         UUID NOT NULL REFERENCES cluster.nodes(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL,
    cpu_percent     NUMERIC(5,2),
    ram_used_mb     BIGINT,
    tasks_running   INT,
    queue_depth     INT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (node_id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE cluster.node_heartbeats_2026_10 PARTITION OF cluster.node_heartbeats
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE cluster.node_heartbeats_2026_11 PARTITION OF cluster.node_heartbeats
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE TABLE cluster.node_state_changes (
    id              BIGSERIAL PRIMARY KEY,
    node_id         UUID NOT NULL REFERENCES cluster.nodes(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_by      UUID REFERENCES core.users(id),
    field           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    reason          TEXT,
    source          TEXT NOT NULL
);
CREATE INDEX idx_node_state_changes_node ON cluster.node_state_changes(node_id, ts DESC);
CREATE INDEX idx_node_state_changes_actor ON cluster.node_state_changes(changed_by, ts DESC);

CREATE TABLE cluster.master_replication (
    master_node_id  UUID PRIMARY KEY REFERENCES core.master_nodes(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    upstream_node_id UUID REFERENCES core.master_nodes(id),
    replication_lag_seconds INT,
    last_check_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_healthy      BOOLEAN NOT NULL DEFAULT TRUE,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (master_node_id <> upstream_node_id)
);

CREATE TABLE cluster.node_spaces (
    node_id         UUID NOT NULL REFERENCES cluster.nodes(id) ON DELETE CASCADE,
    space_id        UUID NOT NULL REFERENCES core.spaces(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, space_id)
);
CREATE INDEX idx_node_spaces_space ON cluster.node_spaces(space_id);

CREATE OR REPLACE VIEW cluster.exclusive_nodes AS
SELECT
    n.id,
    n.node_name,
    n.node_kind,
    n.status,
    n.desired_state,
    min(ns.space_id) AS exclusive_space_id
FROM cluster.nodes n
JOIN cluster.node_spaces ns ON ns.node_id = n.id
GROUP BY n.id
HAVING count(*) = 1;

CREATE OR REPLACE VIEW cluster.live_nodes AS
SELECT
    n.id,
    n.node_name,
    n.node_kind,
    n.hostname,
    n.role,
    n.worker_group,
    n.status,
    n.desired_state,
    n.accepts_new_tasks,
    n.last_heartbeat_at,
    EXTRACT(EPOCH FROM (now() - n.last_heartbeat_at)) AS seconds_since_heartbeat,
    CASE
        WHEN n.status = 'stopped' THEN 'stopped'
        WHEN now() - n.last_heartbeat_at > (n.heartbeat_interval_seconds * 3) * INTERVAL '1 second'
            THEN 'unresponsive'
        ELSE 'alive'
    END AS liveness,
    n.metadata
FROM cluster.nodes n
WHERE n.status NOT IN ('stopped', 'offline');

CREATE OR REPLACE FUNCTION cluster.register_node(
    p_node_name     TEXT,
    p_node_kind     TEXT,
    p_hostname      TEXT,
    p_pid           INT,
    p_master_node_id UUID DEFAULT NULL,
    p_role          TEXT DEFAULT 'worker',
    p_worker_group  TEXT DEFAULT NULL,
    p_runtime       TEXT DEFAULT 'systemd',
    p_metadata      JSONB DEFAULT '{}'::jsonb,
    p_heartbeat_interval_seconds INT DEFAULT 30
)
RETURNS UUID
LANGUAGE plpgsql
SET search_path = cluster
AS $$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO cluster.nodes (
        node_name, node_kind, hostname, pid,
        master_node_id, role, worker_group,
        runtime, metadata, heartbeat_interval_seconds,
        status, last_heartbeat_at
    ) VALUES (
        p_node_name, p_node_kind, p_hostname, p_pid,
        p_master_node_id, p_role, p_worker_group,
        p_runtime, p_metadata, p_heartbeat_interval_seconds,
        'online', now()
    )
    ON CONFLICT (node_name, hostname, pid) DO UPDATE
       SET status = 'online',
           last_heartbeat_at = now(),
           metadata = EXCLUDED.metadata,
           updated_at = now()
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION cluster.mark_dead_nodes(
    p_multiplier INT DEFAULT 3
)
RETURNS INT
LANGUAGE plpgsql
SET search_path = cluster
AS $$
DECLARE
    affected INT;
BEGIN
    WITH dead AS (
        UPDATE cluster.nodes
           SET status = 'offline',
               status_reason = 'heartbeat_timeout',
               updated_at = now()
         WHERE status IN ('online', 'draining')
           AND now() - last_heartbeat_at
               > (heartbeat_interval_seconds * p_multiplier) * INTERVAL '1 second'
        RETURNING id
    )
    INSERT INTO cluster.node_state_changes (node_id, field, old_value, new_value, reason, source)
    SELECT id, 'status', 'online', 'offline', 'heartbeat_timeout', 'auto'
      FROM dead;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

CREATE OR REPLACE FUNCTION cluster.set_node_desired_state(
    p_node_id       UUID,
    p_actor_id      UUID,
    p_new_state     TEXT,
    p_reason        TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET search_path = cluster, core
AS $$
DECLARE
    old_state TEXT;
    is_exclusive BOOLEAN;
    actor_is_global_admin BOOLEAN;
BEGIN
    SELECT desired_state INTO old_state FROM cluster.nodes WHERE id = p_node_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Node % not found', p_node_id;
    END IF;

    SELECT EXISTS (SELECT 1 FROM cluster.exclusive_nodes WHERE id = p_node_id)
      INTO is_exclusive;

    SELECT EXISTS (
        SELECT 1 FROM core.effective_permissions(p_actor_id, NULL)
        WHERE permission_code = 'cluster.manage_all'
    ) INTO actor_is_global_admin;

    IF NOT actor_is_global_admin AND NOT is_exclusive THEN
        RAISE EXCEPTION
            'Node % is shared between multiple spaces; only global admin can manage it',
            p_node_id;
    END IF;

    UPDATE cluster.nodes
       SET desired_state = p_new_state,
           accepts_new_tasks = (p_new_state = 'running'),
           updated_at = now()
     WHERE id = p_node_id;

    INSERT INTO cluster.node_state_changes (
        node_id, changed_by, field, old_value, new_value, reason, source
    ) VALUES (
        p_node_id, p_actor_id, 'desired_state',
        old_state, p_new_state,
        COALESCE(p_reason, 'manual change via webui'),
        'webui'
    );

    PERFORM pg_notify('node_control', json_build_object(
        'node_id', p_node_id,
        'action', 'desired_state_changed',
        'new_state', p_new_state
    )::text);

    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION cluster.promote_to_primary(
    p_node_kind     TEXT,
    p_worker_group  TEXT,
    p_new_primary_id UUID,
    p_actor_id      UUID
)
RETURNS INT
LANGUAGE plpgsql
SET search_path = cluster, core
AS $$
DECLARE
    demoted INT;
BEGIN
    WITH demoted_rows AS (
        UPDATE cluster.nodes
           SET role = 'replica',
               updated_at = now()
         WHERE node_kind = p_node_kind
           AND worker_group = p_worker_group
           AND role = 'primary'
           AND id <> p_new_primary_id
        RETURNING id
    )
    INSERT INTO cluster.node_state_changes (node_id, changed_by, field, old_value, new_value, reason, source)
    SELECT id, p_actor_id, 'role', 'primary', 'replica', 'promotion of another node', 'webui'
      FROM demoted_rows;

    GET DIAGNOSTICS demoted = ROW_COUNT;

    UPDATE cluster.nodes
       SET role = 'primary',
           updated_at = now()
     WHERE id = p_new_primary_id
       AND node_kind = p_node_kind
       AND worker_group = p_worker_group;

    INSERT INTO cluster.node_state_changes (node_id, changed_by, field, old_value, new_value, reason, source)
    VALUES (p_new_primary_id, p_actor_id, 'role', 'replica', 'primary', 'manual promotion', 'webui');

    PERFORM pg_notify('node_control', json_build_object(
        'action', 'promote',
        'node_id', p_new_primary_id,
        'node_kind', p_node_kind,
        'worker_group', p_worker_group
    )::text);

    RETURN demoted;
END;
$$;

-- ---------------------------------------------------------------------
-- 6. INVENTORY
-- ---------------------------------------------------------------------
CREATE TABLE inventory.servers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname        TEXT NOT NULL UNIQUE,
    ip_address      INET,
    os_family       TEXT NOT NULL,
    os_version      TEXT,
    environment     TEXT,
    datacenter      TEXT,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    description     TEXT,
    ssh_port        INT NOT NULL DEFAULT 22,
    ssh_user        TEXT,
    ssh_key_id      UUID,
    winrm_port      INT,
    status          TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at    TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_servers_env ON inventory.servers(environment) WHERE deleted_at IS NULL;
CREATE INDEX idx_servers_tags ON inventory.servers USING GIN(tags);
CREATE INDEX idx_servers_status ON inventory.servers(status) WHERE deleted_at IS NULL;

CREATE TABLE inventory.server_groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        CITEXT NOT NULL UNIQUE,
    description TEXT,
    filter_expr JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory.server_group_members (
    group_id    UUID NOT NULL REFERENCES inventory.server_groups(id) ON DELETE CASCADE,
    server_id   UUID NOT NULL REFERENCES inventory.servers(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, server_id)
);

CREATE TABLE inventory.credentials (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        CITEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,
    encrypted   BYTEA NOT NULL,
    encryption_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by  UUID REFERENCES core.users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);

ALTER TABLE inventory.servers
    ADD CONSTRAINT fk_servers_ssh_key
    FOREIGN KEY (ssh_key_id) REFERENCES inventory.credentials(id) ON DELETE SET NULL;

CREATE TABLE inventory.server_space_access (
    server_id       UUID NOT NULL REFERENCES inventory.servers(id) ON DELETE CASCADE,
    space_id        UUID NOT NULL REFERENCES core.spaces(id) ON DELETE CASCADE,
    access_level    TEXT NOT NULL DEFAULT 'manage',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (server_id, space_id)
);

-- ---------------------------------------------------------------------
-- 7. AUTOMATION: команды, playbook, шаблоны
-- ---------------------------------------------------------------------
CREATE TABLE automation.commands (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    name            CITEXT NOT NULL,
    description     TEXT,
    language        TEXT NOT NULL,
    current_version_id UUID,
    owner_id        UUID REFERENCES core.users(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (space_id, name)
);
CREATE INDEX idx_commands_space ON automation.commands(space_id) WHERE deleted_at IS NULL;

CREATE TABLE automation.command_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_id      UUID NOT NULL REFERENCES automation.commands(id) ON DELETE CASCADE,
    version         INT NOT NULL,
    code            TEXT NOT NULL,
    parameters_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    requirements    JSONB NOT NULL DEFAULT '{}'::jsonb,
    commit_message  TEXT,
    author_id       UUID REFERENCES core.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_id, version)
);
CREATE INDEX idx_command_versions_command ON automation.command_versions(command_id, version DESC);

ALTER TABLE automation.commands
    ADD CONSTRAINT fk_commands_current_version
    FOREIGN KEY (current_version_id) REFERENCES automation.command_versions(id) ON DELETE SET NULL;

CREATE TABLE automation.command_targets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    command_id  UUID NOT NULL REFERENCES automation.commands(id) ON DELETE CASCADE,
    server_id   UUID REFERENCES inventory.servers(id) ON DELETE CASCADE,
    group_id    UUID REFERENCES inventory.server_groups(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (server_id IS NOT NULL OR group_id IS NOT NULL)
);

CREATE TABLE automation.playbooks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    name            CITEXT NOT NULL,
    description     TEXT,
    kind            TEXT NOT NULL,
    manifest        JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_version_id UUID,
    owner_id        UUID REFERENCES core.users(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (space_id, name)
);
CREATE INDEX idx_playbooks_space ON automation.playbooks(space_id) WHERE deleted_at IS NULL;

CREATE TABLE automation.playbook_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playbook_id     UUID NOT NULL REFERENCES automation.playbooks(id) ON DELETE CASCADE,
    version         INT NOT NULL,
    content         TEXT NOT NULL,
    files           JSONB NOT NULL DEFAULT '[]'::jsonb,
    commit_message  TEXT,
    author_id       UUID REFERENCES core.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (playbook_id, version)
);

ALTER TABLE automation.playbooks
    ADD CONSTRAINT fk_playbooks_current_version
    FOREIGN KEY (current_version_id) REFERENCES automation.playbook_versions(id) ON DELETE SET NULL;

CREATE TABLE automation.config_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    name            CITEXT NOT NULL,
    description     TEXT,
    engine          TEXT NOT NULL DEFAULT 'jinja2',
    content         TEXT NOT NULL,
    variables_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (space_id, name)
);

-- ---------------------------------------------------------------------
-- 8. TASKS
-- ---------------------------------------------------------------------
CREATE TABLE tasks.tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       UUID REFERENCES tasks.tasks(id) ON DELETE SET NULL,
    root_id         UUID,
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    kind            TEXT NOT NULL,
    command_id      UUID REFERENCES automation.commands(id),
    command_version_id UUID REFERENCES automation.command_versions(id),
    playbook_id     UUID REFERENCES automation.playbooks(id),
    playbook_version_id UUID REFERENCES automation.playbook_versions(id),
    target_server_id UUID REFERENCES inventory.servers(id),
    target_group_id  UUID REFERENCES inventory.server_groups(id),
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_mode  TEXT NOT NULL DEFAULT 'async',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_by      UUID REFERENCES core.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    queued_at       TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    exit_code       INT,
    result          JSONB,
    error           TEXT,
    worker_id       TEXT,
    idempotency_key TEXT,
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_tasks_parent ON tasks.tasks(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX idx_tasks_root ON tasks.tasks(root_id);
CREATE INDEX idx_tasks_status ON tasks.tasks(status)
    WHERE status IN ('pending','queued','running');
CREATE INDEX idx_tasks_created_at ON tasks.tasks(created_at DESC);
CREATE INDEX idx_tasks_server ON tasks.tasks(target_server_id, created_at DESC);
CREATE INDEX idx_tasks_user ON tasks.tasks(created_by, created_at DESC);
CREATE INDEX idx_tasks_space ON tasks.tasks(space_id, created_at DESC);
CREATE UNIQUE INDEX idx_tasks_idempotency
    ON tasks.tasks(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE tasks.task_logs (
    id          BIGSERIAL,
    task_id     UUID NOT NULL REFERENCES tasks.tasks(id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    stream      TEXT NOT NULL DEFAULT 'stdout',
    level       TEXT,
    message     TEXT NOT NULL,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE TABLE tasks.task_logs_2026_10 PARTITION OF tasks.task_logs
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE tasks.task_logs_2026_11 PARTITION OF tasks.task_logs
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE INDEX idx_task_logs_task ON tasks.task_logs(task_id, ts);

CREATE TABLE tasks.task_dependencies (
    task_id         UUID NOT NULL REFERENCES tasks.tasks(id) ON DELETE CASCADE,
    depends_on_id   UUID NOT NULL REFERENCES tasks.tasks(id) ON DELETE CASCADE,
    mode            TEXT NOT NULL DEFAULT 'sync',
    condition       TEXT NOT NULL DEFAULT 'on_success',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id <> depends_on_id)
);
CREATE INDEX idx_task_deps_depends_on ON tasks.task_dependencies(depends_on_id);

-- ---------------------------------------------------------------------
-- 9. SCHEDULING
-- ---------------------------------------------------------------------
CREATE TABLE scheduling.schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    name            CITEXT NOT NULL,
    description     TEXT,
    kind            TEXT NOT NULL,
    command_id      UUID REFERENCES automation.commands(id),
    playbook_id     UUID REFERENCES automation.playbooks(id),
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_server_id UUID REFERENCES inventory.servers(id),
    target_group_id  UUID REFERENCES inventory.server_groups(id),
    cron_expr       TEXT,
    interval_seconds INT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    created_by      UUID REFERENCES core.users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (space_id, name),
    CHECK (cron_expr IS NOT NULL OR interval_seconds IS NOT NULL)
);
CREATE INDEX idx_schedules_active ON scheduling.schedules(next_run_at) WHERE is_active;

-- ---------------------------------------------------------------------
-- 10. DRIFT
-- ---------------------------------------------------------------------
CREATE TABLE drift.desired_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id       UUID NOT NULL REFERENCES inventory.servers(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    content         TEXT,
    source_playbook_id UUID REFERENCES automation.playbooks(id),
    drift_policy    TEXT NOT NULL DEFAULT 'alert',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (server_id, path)
);
CREATE INDEX idx_desired_state_server ON drift.desired_state(server_id);

CREATE TABLE drift.actual_state (
    server_id       UUID NOT NULL REFERENCES inventory.servers(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (server_id, path)
);

CREATE TABLE drift.drift_incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id       UUID NOT NULL REFERENCES inventory.servers(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    expected_hash   TEXT NOT NULL,
    actual_hash     TEXT NOT NULL,
    diff            TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    resolved_by     UUID REFERENCES core.users(id),
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_drift_open ON drift.drift_incidents(server_id, detected_at DESC)
    WHERE status = 'open';

-- ---------------------------------------------------------------------
-- 11. LOCKS
-- ---------------------------------------------------------------------
CREATE TABLE locks.resource_locks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    resource_path   TEXT,
    space_id        UUID NOT NULL REFERENCES core.spaces(id),
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES core.sessions(id) ON DELETE SET NULL,
    lock_type       TEXT NOT NULL DEFAULT 'exclusive',
    client_info     JSONB NOT NULL DEFAULT '{}'::jsonb,
    acquired_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    ttl_seconds     INT NOT NULL DEFAULT 300,
    released_at     TIMESTAMPTZ,
    released_reason TEXT,
    context         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE UNIQUE INDEX uniq_active_exclusive_lock
    ON locks.resource_locks(resource_type, resource_id, space_id)
    WHERE released_at IS NULL AND lock_type = 'exclusive';
CREATE INDEX idx_locks_expires ON locks.resource_locks(expires_at)
    WHERE released_at IS NULL;
CREATE INDEX idx_locks_space_active ON locks.resource_locks(space_id, resource_type)
    WHERE released_at IS NULL;
CREATE INDEX idx_locks_user_active ON locks.resource_locks(user_id)
    WHERE released_at IS NULL;

CREATE TABLE locks.lock_history (
    id              BIGSERIAL,
    lock_id         UUID NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    space_id        UUID NOT NULL,
    user_id         UUID NOT NULL,
    acquired_at     TIMESTAMPTZ NOT NULL,
    released_at     TIMESTAMPTZ NOT NULL,
    held_seconds    INT NOT NULL,
    released_reason TEXT NOT NULL,
    client_info     JSONB,
    PRIMARY KEY (id, acquired_at)
) PARTITION BY RANGE (acquired_at);

CREATE TABLE locks.lock_history_2026_10 PARTITION OF locks.lock_history
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE locks.lock_history_2026_11 PARTITION OF locks.lock_history
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

CREATE OR REPLACE FUNCTION locks.acquire(
    p_resource_type TEXT,
    p_resource_id   TEXT,
    p_space_id      UUID,
    p_user_id       UUID,
    p_session_id    UUID DEFAULT NULL,
    p_ttl_seconds   INT DEFAULT 300,
    p_lock_type     TEXT DEFAULT 'exclusive',
    p_client_info   JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    lock_id UUID, acquired BOOLEAN,
    held_by_user UUID, held_by_username TEXT,
    expires_at TIMESTAMPTZ, reason TEXT
)
LANGUAGE plpgsql
SET search_path = locks, core
AS $$
DECLARE
    existing RECORD;
    new_lock_id UUID;
BEGIN
    UPDATE locks.resource_locks
       SET released_at = now(), released_reason = 'expired'
     WHERE resource_type = p_resource_type
       AND resource_id = p_resource_id
       AND space_id = p_space_id
       AND released_at IS NULL
       AND expires_at < now();

    SELECT * INTO existing FROM locks.resource_locks
     WHERE resource_type = p_resource_type
       AND resource_id = p_resource_id
       AND space_id = p_space_id
       AND released_at IS NULL
       AND lock_type = 'exclusive'
     FOR UPDATE;

    IF FOUND THEN
        IF existing.user_id = p_user_id THEN
            UPDATE locks.resource_locks
               SET last_heartbeat_at = now(),
                   expires_at = now() + make_interval(secs => p_ttl_seconds)
             WHERE id = existing.id;
            RETURN QUERY SELECT existing.id, true, existing.user_id,
                (SELECT username FROM core.users WHERE id = existing.user_id),
                now() + make_interval(secs => p_ttl_seconds), 'renewed'::text;
            RETURN;
        END IF;
        RETURN QUERY SELECT existing.id, false, existing.user_id,
            (SELECT username FROM core.users WHERE id = existing.user_id),
            existing.expires_at, 'locked_by_other'::text;
        RETURN;
    END IF;

    INSERT INTO locks.resource_locks (
        resource_type, resource_id, space_id,
        user_id, session_id, lock_type,
        client_info, expires_at, ttl_seconds
    ) VALUES (
        p_resource_type, p_resource_id, p_space_id,
        p_user_id, p_session_id, p_lock_type,
        p_client_info,
        now() + make_interval(secs => p_ttl_seconds),
        p_ttl_seconds
    ) RETURNING id INTO new_lock_id;

    RETURN QUERY SELECT new_lock_id, true, p_user_id,
        (SELECT username FROM core.users WHERE id = p_user_id),
        now() + make_interval(secs => p_ttl_seconds), 'acquired'::text;
END;
$$;

CREATE OR REPLACE FUNCTION locks.heartbeat(
    p_lock_id UUID, p_user_id UUID, p_ttl_seconds INT DEFAULT 300
)
RETURNS TABLE (extended BOOLEAN, expires_at TIMESTAMPTZ, reason TEXT)
LANGUAGE plpgsql
SET search_path = locks
AS $$
DECLARE
    updated INT;
    new_expires TIMESTAMPTZ;
BEGIN
    new_expires := now() + make_interval(secs => p_ttl_seconds);
    UPDATE locks.resource_locks
       SET last_heartbeat_at = now(), expires_at = new_expires
     WHERE id = p_lock_id
       AND user_id = p_user_id
       AND released_at IS NULL
       AND expires_at > now();
    GET DIAGNOSTICS updated = ROW_COUNT;
    IF updated = 0 THEN
        RETURN QUERY SELECT false, NULL::TIMESTAMPTZ, 'lock_lost'::text;
    ELSE
        RETURN QUERY SELECT true, new_expires, 'renewed'::text;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION locks.release(
    p_lock_id UUID,
    p_user_id UUID DEFAULT NULL,
    p_reason TEXT DEFAULT 'user_exit'
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET search_path = locks
AS $$
DECLARE
    lock_row RECORD;
BEGIN
    SELECT * INTO lock_row FROM locks.resource_locks
     WHERE id = p_lock_id AND released_at IS NULL
     FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF p_user_id IS NOT NULL AND lock_row.user_id <> p_user_id THEN
        RAISE EXCEPTION 'Cannot release lock owned by another user';
    END IF;
    UPDATE locks.resource_locks
       SET released_at = now(), released_reason = p_reason
     WHERE id = p_lock_id;

    INSERT INTO locks.lock_history (
        lock_id, resource_type, resource_id, space_id,
        user_id, acquired_at, released_at, held_seconds,
        released_reason, client_info
    ) VALUES (
        lock_row.id, lock_row.resource_type, lock_row.resource_id, lock_row.space_id,
        lock_row.user_id, lock_row.acquired_at, now(),
        EXTRACT(EPOCH FROM (now() - lock_row.acquired_at))::INT,
        p_reason, lock_row.client_info
    );
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION locks.cleanup_expired()
RETURNS INT
LANGUAGE plpgsql
SET search_path = locks
AS $$
DECLARE
    affected INT;
BEGIN
    WITH expired AS (
        UPDATE locks.resource_locks
           SET released_at = now(), released_reason = 'expired'
         WHERE released_at IS NULL AND expires_at < now()
        RETURNING *
    )
    INSERT INTO locks.lock_history (
        lock_id, resource_type, resource_id, space_id,
        user_id, acquired_at, released_at, held_seconds,
        released_reason, client_info
    )
    SELECT id, resource_type, resource_id, space_id, user_id,
           acquired_at, released_at,
           EXTRACT(EPOCH FROM (released_at - acquired_at))::INT,
           released_reason, client_info
      FROM expired;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

-- ---------------------------------------------------------------------
-- 12. SYNC
-- ---------------------------------------------------------------------
CREATE TABLE sync.file_sync_log (
    id              BIGSERIAL PRIMARY KEY,
    space_id        UUID NOT NULL,
    master_node_id  UUID NOT NULL REFERENCES core.master_nodes(id),
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    operation       TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    status          TEXT NOT NULL,
    error           TEXT,
    duration_ms     INT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    synced_by       TEXT NOT NULL
);
CREATE INDEX idx_sync_log_space ON sync.file_sync_log(space_id, synced_at DESC);
CREATE INDEX idx_sync_log_resource ON sync.file_sync_log(resource_type, resource_id, synced_at DESC);

CREATE TABLE sync.file_state (
    master_node_id  UUID NOT NULL REFERENCES core.master_nodes(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    size_bytes      BIGINT,
    mtime           TIMESTAMPTZ,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (master_node_id, file_path)
);
CREATE INDEX idx_file_state_hash ON sync.file_state(content_hash);

CREATE TABLE sync.sync_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_node_id  UUID NOT NULL REFERENCES core.master_nodes(id) ON DELETE CASCADE,
    space_id        UUID NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    operation       TEXT NOT NULL,
    payload_ref     UUID,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INT NOT NULL DEFAULT 0,
    max_attempts    INT NOT NULL DEFAULT 5,
    scheduled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sync_queue_pending
    ON sync.sync_queue(master_node_id, scheduled_at)
    WHERE status IN ('pending', 'failed');

CREATE TABLE sync.drift_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_node_id  UUID NOT NULL REFERENCES core.master_nodes(id),
    file_path       TEXT NOT NULL,
    expected_hash   TEXT NOT NULL,
    actual_hash     TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    resolution      TEXT,
    resolved_by     UUID REFERENCES core.users(id)
);
CREATE INDEX idx_sync_drift_open ON sync.drift_events(master_node_id, detected_at DESC)
    WHERE resolved_at IS NULL;

-- Триггер: постановка sync-задачи при изменении playbook
CREATE OR REPLACE FUNCTION sync.enqueue_playbook_sync()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    node RECORD;
    new_space_id UUID;
    new_id UUID;
    op TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        new_space_id := OLD.space_id;
        new_id := OLD.id;
        op := 'delete';
    ELSE
        new_space_id := NEW.space_id;
        new_id := NEW.id;
        op := CASE TG_OP WHEN 'INSERT' THEN 'create' ELSE 'update' END;
    END IF;

    FOR node IN
        SELECT master_node_id FROM core.space_master_nodes WHERE space_id = new_space_id
    LOOP
        INSERT INTO sync.sync_queue (
            master_node_id, space_id, resource_type, resource_id, operation, payload_ref
        ) VALUES (
            node.master_node_id, new_space_id, 'playbook', new_id::text, op, new_id
        );
    END LOOP;

    PERFORM pg_notify('sync_queue', json_build_object(
        'space_id', new_space_id, 'resource_type', 'playbook', 'resource_id', new_id
    )::text);

    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_playbook_sync
    AFTER INSERT OR UPDATE OR DELETE ON automation.playbooks
    FOR EACH ROW EXECUTE FUNCTION sync.enqueue_playbook_sync();

-- ---------------------------------------------------------------------
-- 13. AUTH: OAuth
-- ---------------------------------------------------------------------
CREATE TABLE auth.oauth_clients (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           TEXT NOT NULL UNIQUE,
    client_secret_hash  TEXT,
    name                CITEXT NOT NULL,
    description         TEXT,
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,
    redirect_uris       TEXT[] NOT NULL DEFAULT '{}',
    grant_types         TEXT[] NOT NULL DEFAULT '{authorization_code,refresh_token}',
    allowed_scopes      TEXT[] NOT NULL DEFAULT '{}',
    access_token_ttl    INT NOT NULL DEFAULT 900,
    refresh_token_ttl   INT NOT NULL DEFAULT 2592000,
    require_pkce        BOOLEAN NOT NULL DEFAULT TRUE,
    owner_id            UUID REFERENCES core.users(id),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_oauth_clients_active ON auth.oauth_clients(is_active);

CREATE TABLE auth.refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash      TEXT NOT NULL UNIQUE,
    client_id       UUID NOT NULL REFERENCES auth.oauth_clients(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    family_id       UUID NOT NULL,
    used_at         TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    user_agent      TEXT,
    ip_address      INET,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_tokens_family ON auth.refresh_tokens(family_id);
CREATE INDEX idx_refresh_tokens_user ON auth.refresh_tokens(user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_refresh_tokens_expires ON auth.refresh_tokens(expires_at) WHERE revoked_at IS NULL;

CREATE TABLE auth.access_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash  TEXT NOT NULL UNIQUE,
    client_id   UUID NOT NULL REFERENCES auth.oauth_clients(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_access_tokens_expires ON auth.access_tokens(expires_at) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------
-- 14. MONITORING
-- ---------------------------------------------------------------------
CREATE TABLE monitoring.metrics (
    ts          TIMESTAMPTZ NOT NULL,
    metric      TEXT NOT NULL,
    labels      JSONB NOT NULL DEFAULT '{}'::jsonb,
    value       DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ts, metric)
);

CREATE TABLE monitoring.integrations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        CITEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    credentials_id UUID REFERENCES inventory.credentials(id),
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE monitoring.alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id  UUID NOT NULL REFERENCES monitoring.integrations(id) ON DELETE CASCADE,
    external_id     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    server_id       UUID REFERENCES inventory.servers(id),
    labels          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'open',
    started_at      TIMESTAMPTZ NOT NULL,
    resolved_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (integration_id, external_id)
);
CREATE INDEX idx_alerts_status ON monitoring.alerts(status, severity);

-- ---------------------------------------------------------------------
-- 15. REPORTING: views
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting.active_tasks AS
SELECT
    t.id, t.status, t.kind,
    c.name AS command_name,
    s.hostname AS target_server,
    u.username AS created_by,
    t.created_at, t.started_at,
    EXTRACT(EPOCH FROM (now() - t.started_at)) AS running_seconds
FROM tasks.tasks t
LEFT JOIN automation.commands c ON c.id = t.command_id
LEFT JOIN inventory.servers s ON s.id = t.target_server_id
LEFT JOIN core.users u ON u.id = t.created_by
WHERE t.status IN ('pending','queued','running')
  AND t.deleted_at IS NULL;

CREATE OR REPLACE VIEW reporting.task_tree AS
WITH RECURSIVE tree AS (
    SELECT t.id, t.parent_id, t.root_id, t.status,
           t.created_at, t.finished_at, 0 AS depth, ARRAY[t.id] AS path
    FROM tasks.tasks t WHERE t.parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.root_id, c.status,
           c.created_at, c.finished_at, p.depth + 1, p.path || c.id
    FROM tasks.tasks c JOIN tree p ON c.parent_id = p.id
)
SELECT * FROM tree;

CREATE OR REPLACE VIEW reporting.open_drift AS
SELECT
    d.id, s.hostname, s.environment, d.path,
    d.expected_hash, d.actual_hash, d.detected_at, ds.drift_policy
FROM drift.drift_incidents d
JOIN inventory.servers s ON s.id = d.server_id
LEFT JOIN drift.desired_state ds
    ON ds.server_id = d.server_id AND ds.path = d.path
WHERE d.status = 'open';

CREATE OR REPLACE VIEW reporting.audit_resolved AS
SELECT
    e.id, e.ts, e.action, e.result,
    e.user_id, u.username AS user_username,
    e.resource_type, e.resource_id,
    CASE e.resource_type
        WHEN 'task' THEN (SELECT c.name FROM tasks.tasks t
            LEFT JOIN automation.commands c ON c.id = t.command_id
            WHERE t.id::text = e.resource_id)
        WHEN 'server' THEN (SELECT hostname FROM inventory.servers WHERE id::text = e.resource_id)
        WHEN 'command' THEN (SELECT name FROM automation.commands WHERE id::text = e.resource_id)
        WHEN 'playbook' THEN (SELECT name FROM automation.playbooks WHERE id::text = e.resource_id)
        WHEN 'user' THEN (SELECT username FROM core.users WHERE id::text = e.resource_id)
        ELSE NULL
    END AS resource_name,
    e.ip_address, e.user_agent, e.request_id, e.details
FROM audit.events e
LEFT JOIN core.users u ON u.id = e.user_id;

-- ---------------------------------------------------------------------
-- 16. Триггер updated_at (общий)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION framework.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE t RECORD;
BEGIN
    FOR t IN
        SELECT table_schema, table_name
          FROM information_schema.columns
         WHERE column_name = 'updated_at'
           AND table_schema IN (
               'core','cluster','inventory','automation',
               'tasks','scheduling','drift','auth','monitoring'
           )
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_%s_updated_at
             BEFORE UPDATE ON %I.%I
             FOR EACH ROW EXECUTE FUNCTION framework.set_updated_at()',
            t.table_schema, t.table_name, t.table_schema, t.table_name
        );
    END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- 17. SEED: базовые данные
-- ---------------------------------------------------------------------

-- Источник local
INSERT INTO core.user_sources (code, kind, display_name, priority, managed_attributes)
VALUES ('local', 'local', 'Local accounts', 1000, '{}')
ON CONFLICT (code) DO NOTHING;

-- Базовые роли
INSERT INTO core.roles (name, description, is_system) VALUES
    ('admin',    'Полный доступ ко всей системе',       TRUE),
    ('operator', 'Запуск задач и playbook',             TRUE),
    ('viewer',   'Только чтение',                       TRUE),
    ('space_admin', 'Администратор пространства',       TRUE)
ON CONFLICT (name) DO NOTHING;

-- Базовые права
INSERT INTO core.permissions (code, description) VALUES
    ('cluster.read',           'Просмотр нод кластера'),
    ('cluster.manage',         'Управление нодами пространства'),
    ('cluster.manage_all',     'Управление любой нодой кластера'),
    ('tasks.run',              'Запуск задач'),
    ('tasks.read',             'Просмотр задач'),
    ('tasks.cancel',           'Отмена задач'),
    ('commands.edit',          'Редактирование команд'),
    ('playbooks.edit',         'Редактирование playbook'),
    ('playbooks.run',          'Запуск playbook'),
    ('servers.read',           'Просмотр серверов'),
    ('servers.edit',           'Редактирование серверов'),
    ('servers.delete',         'Удаление серверов'),
    ('schedules.edit',         'Редактирование расписаний'),
    ('drift.resolve',          'Разрешение инцидентов дрейфа'),
    ('users.manage',           'Управление пользователями'),
    ('oauth.manage',           'Управление OAuth-клиентами'),
    ('audit.read',             'Просмотр аудита'),
    ('spaces.manage',          'Управление пространствами')
ON CONFLICT (code) DO NOTHING;

-- Права admin — все
INSERT INTO core.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM core.roles r CROSS JOIN core.permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

-- Operator
INSERT INTO core.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM core.roles r, core.permissions p
WHERE r.name = 'operator'
  AND p.code IN ('tasks.run','tasks.read','tasks.cancel',
                 'playbooks.run','servers.read','schedules.edit',
                 'cluster.read')
ON CONFLICT DO NOTHING;

-- Viewer
INSERT INTO core.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM core.roles r, core.permissions p
WHERE r.name = 'viewer'
  AND p.code IN ('tasks.read','servers.read','cluster.read')
ON CONFLICT DO NOTHING;

-- Space admin
INSERT INTO core.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM core.roles r, core.permissions p
WHERE r.name = 'space_admin'
  AND p.code IN ('tasks.run','tasks.read','tasks.cancel',
                 'commands.edit','playbooks.edit','playbooks.run',
                 'servers.read','servers.edit','schedules.edit',
                 'drift.resolve','cluster.read','cluster.manage')
ON CONFLICT DO NOTHING;

-- Пространство по умолчанию
INSERT INTO core.spaces (code, name, description, settings)
VALUES ('default', 'Default', 'Пространство по умолчанию', '{"default_ttl_seconds": 300}'::jsonb)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------
-- 18. Комментарии к таблицам (для документации в psql \d+)
-- ---------------------------------------------------------------------
COMMENT ON SCHEMA core IS 'Пользователи, роли, пространства, master nodes';
COMMENT ON SCHEMA framework IS 'Миграции, кэш, служебные таблицы';
COMMENT ON SCHEMA audit IS 'Аудит действий пользователей (append-only, партиционирован)';
COMMENT ON SCHEMA cluster IS 'Ноды кластера: webui, scheduler, queue, sync, metrics';
COMMENT ON SCHEMA inventory IS 'Инвентарь целевых серверов';
COMMENT ON SCHEMA automation IS 'Команды, playbook, шаблоны конфигов';
COMMENT ON SCHEMA tasks IS 'Задачи и их логи (партиционированы)';
COMMENT ON SCHEMA scheduling IS 'Расписания (замена cron на целевых серверах)';
COMMENT ON SCHEMA drift IS 'Дрейф конфигов на целевых серверах';
COMMENT ON SCHEMA locks IS 'Блокировки ресурсов при редактировании';
COMMENT ON SCHEMA sync IS 'Синхронизация файлов между БД и master nodes';
COMMENT ON SCHEMA auth IS 'OAuth-клиенты и токены';
COMMENT ON SCHEMA monitoring IS 'Метрики, интеграции с Zabbix/Grafana/OTel';
COMMENT ON SCHEMA reporting IS 'Views для WebUI и дашбордов';

COMMENT ON TABLE core.users IS 'Пользователи. primary_source_id указывает, откуда пришёл пользователь';
COMMENT ON TABLE core.user_identities IS 'Привязка пользователя к источникам (AD, LDAP, OIDC). Один пользователь — несколько identities';
COMMENT ON TABLE core.spaces IS 'Пространства (проекты) — логическая изоляция ресурсов';
COMMENT ON TABLE core.master_nodes IS 'Управляющие серверы (master-db01, master-db01-r)';
COMMENT ON TABLE core.space_master_nodes IS 'Какие master nodes обслуживают какое пространство. os_user — под каким пользователем ОС работают файлы';
COMMENT ON TABLE cluster.nodes IS 'Процессы-воркеры: homer webui:start, queue:start и т.д.';
COMMENT ON TABLE cluster.node_heartbeats IS 'История heartbeat для графиков и SLA';
COMMENT ON TABLE cluster.node_state_changes IS 'Журнал изменений состояния нод (кто, что, когда)';
COMMENT ON TABLE locks.resource_locks IS 'Активные блокировки редактирования. TTL обязателен, cleanup снимает протухшие';
COMMENT ON TABLE sync.sync_queue IS 'Очередь синхронизации файлов из БД на master nodes';
