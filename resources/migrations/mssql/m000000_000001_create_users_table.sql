-- ── users ─────────────────────────────────────────
CREATE TABLE users (
    id            BIGINT IDENTITY(1,1) NOT NULL
                  CONSTRAINT PK_users PRIMARY KEY,
    username      NVARCHAR(255) NOT NULL
                  CONSTRAINT UQ_users_username UNIQUE,
    display_name  NVARCHAR(255) NULL,
    email         NVARCHAR(255) NULL,
    locale        NVARCHAR(16)  NULL,
    password_hash NVARCHAR(255) NULL,
    provider      NVARCHAR(32)  NOT NULL
                  CONSTRAINT DF_users_provider DEFAULT 'local',
    enabled       BIT           NOT NULL
                  CONSTRAINT DF_users_enabled  DEFAULT 1,
    created_at    DATETIME2(6)  NOT NULL
                  CONSTRAINT DF_users_created_at DEFAULT SYSUTCDATETIME(),
    updated_at    DATETIME2(6)  NULL
);
GO

-- ── roles ─────────────────────────────────────────
CREATE TABLE roles (
    id            BIGINT IDENTITY(1,1) NOT NULL
                  CONSTRAINT PK_roles PRIMARY KEY,
    name          NVARCHAR(64)  NOT NULL
                  CONSTRAINT UQ_roles_name UNIQUE,
    display_name  NVARCHAR(255) NULL,
    permissions   NVARCHAR(MAX) NULL,
    builtin       BIT           NOT NULL
                  CONSTRAINT DF_roles_builtin    DEFAULT 0,
    created_at    DATETIME2(6)  NOT NULL
                  CONSTRAINT DF_roles_created_at DEFAULT SYSUTCDATETIME()
);
GO

-- ── user_roles ────────────────────────────────────
CREATE TABLE user_roles (
    user_id  BIGINT NOT NULL,
    role_id  BIGINT NOT NULL,
    CONSTRAINT PK_user_roles PRIMARY KEY (user_id, role_id),
    CONSTRAINT FK_user_roles_users FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT FK_user_roles_roles FOREIGN KEY (role_id)
        REFERENCES roles (id) ON DELETE CASCADE
);
GO

-- ── sessions ──────────────────────────────────────
CREATE TABLE sessions (
    id         NVARCHAR(64)  NOT NULL
               CONSTRAINT PK_sessions PRIMARY KEY,
    user_id    BIGINT        NOT NULL,
    created_at DATETIME2(6)  NOT NULL
               CONSTRAINT DF_sessions_created_at DEFAULT SYSUTCDATETIME(),
    expires_at DATETIME2(6)  NOT NULL,
    ip         NVARCHAR(64)  NULL,
    user_agent NVARCHAR(MAX) NULL,
    CONSTRAINT FK_sessions_users FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE
);
GO

CREATE INDEX idx_sessions_user ON sessions (user_id);
GO
