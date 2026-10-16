"""
Editor locks.

Each editable target (file or config key) can be locked by one user
for a limited time. The lock is renewed by the client periodically.
If the lease expires, the lock is considered free.
"""
from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from homer.db import connect, BaseDB, DBError


DDL = {
    "sqlite": """
        CREATE TABLE IF NOT EXISTS homer_editor_locks (
            resource   TEXT PRIMARY KEY,
            owner      TEXT NOT NULL,
            token      TEXT NOT NULL,
            locked_at  TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            client_ip  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_editor_locks_expires
            ON homer_editor_locks(expires_at);
    """,
    "postgres": """
        CREATE TABLE IF NOT EXISTS homer_editor_locks (
            resource   VARCHAR(512) PRIMARY KEY,
            owner      VARCHAR(255) NOT NULL,
            token      VARCHAR(64) NOT NULL,
            locked_at  TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            client_ip  VARCHAR(64)
        );
        CREATE INDEX IF NOT EXISTS idx_editor_locks_expires
            ON homer_editor_locks(expires_at);
    """,
    "mysql": """
        CREATE TABLE IF NOT EXISTS homer_editor_locks (
            resource   VARCHAR(512) PRIMARY KEY,
            owner      VARCHAR(255) NOT NULL,
            token      VARCHAR(64) NOT NULL,
            locked_at  DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            client_ip  VARCHAR(64)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        CREATE INDEX idx_editor_locks_expires ON homer_editor_locks(expires_at);
    """,
    "oracle": """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_editor_locks (
                    resource   VARCHAR2(512) PRIMARY KEY,
                    owner      VARCHAR2(255) NOT NULL,
                    token      VARCHAR2(64) NOT NULL,
                    locked_at  TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    client_ip  VARCHAR2(64)
                )';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
    """,
}


@dataclass
class LockInfo:
    resource: str
    owner: str
    token: str
    locked_at: datetime
    expires_at: datetime
    client_ip: Optional[str] = None


class LockError(Exception):
    pass


class LockStore:
    def __init__(self, config, db: Optional[BaseDB] = None):
        self.config = config
        self._external_db = db is not None
        self.db = db or self._build_db()
        if not self.db.is_connected:
            self.db.connect()
        self._init_schema()

    def _build_db(self):
        sched_cfg = self.config.get("scheduler", {}) or {}
        driver = sched_cfg.get("storage", "sqlite")
        conn_cfg = sched_cfg.get(driver) or self.config.get(f"databases.{driver}")
        if driver == "sqlite":
            if not conn_cfg:
                conn_cfg = {"path": "var/cache/homer.db"}
            elif "path" not in conn_cfg:
                conn_cfg = dict(conn_cfg, path="var/cache/homer.db")
        return connect(driver, conn_cfg)

    def _driver(self):
        return self.db.driver_name

    def _ph(self, idx):
        style = self.db._placeholder_style
        if style == ":name":
            return f":{idx + 1}"
        if style == "?":
            return "?"
        return "%s"

    def _init_schema(self):
        ddl = DDL.get(self._driver())
        if not ddl:
            raise DBError(f"No DDL for {self._driver()}")
        if self._driver() == "oracle":
            cur = self.db.cursor()
            try:
                cur.execute(ddl)
            except Exception:
                pass
            finally:
                try: cur.close()
                except Exception: pass
        else:
            for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                try:
                    self.db.execute(stmt)
                except Exception:
                    pass
        self.db.commit()

    # ─────────── API ───────────

    def acquire(self, resource: str, owner: str,
                ttl_seconds: int = 300,
                client_ip: Optional[str] = None) -> LockInfo:
        """
        Acquire a lock on `resource` for `owner`. If the resource is
        already locked by someone else and not expired, raises LockError.
        Reacquiring by the same owner refreshes the lock.
        """
        now = datetime.now()
        expires = now + timedelta(seconds=ttl_seconds)

        # Cleanup expired
        self._purge_expired()

        existing = self._get(resource)
        if existing and existing.owner != owner:
            if existing.expires_at > now:
                raise LockError(
                    f"Resource is locked by '{existing.owner}' "
                    f"until {existing.expires_at.isoformat()}"
                )

        token = existing.token if existing and existing.owner == owner \
            else uuid.uuid4().hex

        if existing:
            self.db.execute(
                f"UPDATE homer_editor_locks SET "
                f"owner = {self._ph(0)}, "
                f"token = {self._ph(1)}, "
                f"locked_at = {self._ph(2)}, "
                f"expires_at = {self._ph(3)}, "
                f"client_ip = {self._ph(4)} "
                f"WHERE resource = {self._ph(5)}",
                [owner, token, now, expires, client_ip, resource],
            )
        else:
            self.db.execute(
                f"INSERT INTO homer_editor_locks "
                f"(resource, owner, token, locked_at, expires_at, client_ip) "
                f"VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, "
                f"{self._ph(3)}, {self._ph(4)}, {self._ph(5)})",
                [resource, owner, token, now, expires, client_ip],
            )
        self.db.commit()
        return LockInfo(resource, owner, token, now, expires, client_ip)

    def refresh(self, resource: str, owner: str, token: str,
                ttl_seconds: int = 300) -> LockInfo:
        info = self._get(resource)
        if not info:
            raise LockError("Lock not found")
        if info.owner != owner or info.token != token:
            raise LockError("Lock is held by another owner/token")
        return self.acquire(resource, owner, ttl_seconds)

    def release(self, resource: str, owner: str, token: str) -> bool:
        info = self._get(resource)
        if not info:
            return False
        if info.owner != owner or info.token != token:
            raise LockError("Lock is held by another owner/token")
        self.db.execute(
            f"DELETE FROM homer_editor_locks WHERE resource = {self._ph(0)}",
            [resource],
        )
        self.db.commit()
        return True

    def get(self, resource: str) -> Optional[LockInfo]:
        self._purge_expired()
        return self._get(resource)

    def list(self) -> list[LockInfo]:
        self._purge_expired()
        rows = self.db.fetchall(
            "SELECT * FROM homer_editor_locks ORDER BY resource",
            dictionary=True,
        )
        return [self._row_to_lock(r) for r in rows]

    def close(self):
        if not self._external_db:
            self.db.close()

    # ─────────── Internals ───────────

    def _get(self, resource: str) -> Optional[LockInfo]:
        row = self.db.fetchone(
            f"SELECT * FROM homer_editor_locks WHERE resource = {self._ph(0)}",
            [resource], dictionary=True,
        )
        return self._row_to_lock(row) if row else None

    def _purge_expired(self):
        now = datetime.now()
        try:
            self.db.execute(
                f"DELETE FROM homer_editor_locks "
                f"WHERE expires_at < {self._ph(0)}",
                [now],
            )
            self.db.commit()
        except Exception:
            pass

    def _row_to_lock(self, row) -> LockInfo:
        d = dict(row) if not isinstance(row, dict) else row

        def _dt(v):
            if isinstance(v, datetime):
                return v
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v)
                except ValueError:
                    pass
            return v

        return LockInfo(
            resource=d["resource"],
            owner=d["owner"],
            token=d["token"],
            locked_at=_dt(d["locked_at"]),
            expires_at=_dt(d["expires_at"]),
            client_ip=d.get("client_ip"),
        )
