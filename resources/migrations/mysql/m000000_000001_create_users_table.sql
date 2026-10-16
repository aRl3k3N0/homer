CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(255) UNIQUE NOT NULL,
    display_name  VARCHAR(255),
    email         VARCHAR(255),
    password_hash VARCHAR(255),
    provider      VARCHAR(32) NOT NULL DEFAULT 'local',
    enabled       TINYINT(1) NOT NULL DEFAULT 1,
    created_at    DATETIME NOT NULL,
    updated_at    DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS roles (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(64) UNIQUE NOT NULL,
    display_name  VARCHAR(255),
    permissions   TEXT,
    builtin       TINYINT(1) NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id  INT NOT NULL,
    role_id  INT NOT NULL,
    PRIMARY KEY (user_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(64) PRIMARY KEY,
    user_id    INT NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    ip         VARCHAR(64),
    user_agent TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
