"""
Node registry + heartbeat.

Each running Homer process registers itself once and then
refreshes its `last_seen` every N seconds in a background thread.
Nodes whose `last_seen` is older than TTL are considered dead.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from lib.db import connect, BaseDB, DBError


DDL = {
    "sqlite": """
        CREATE TABLE IF NOT EXISTS homer_nodes (
            id           TEXT PRIMARY KEY,
            hostname     TEXT NOT NULL,
            ip           TEXT,
            started_at   TEXT NOT NULL,
            last_seen    TEXT NOT NULL,
            role         TEXT DEFAULT 'worker',
            version      TEXT,
            meta         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_last_seen
            ON homer_nodes(last_seen);
    """,
    "postgres": """
        CREATE TABLE IF NOT EXISTS homer_nodes (
            id           VARCHAR(64) PRIMARY KEY,
            hostname     VARCHAR(255) NOT NULL,
            ip           VARCHAR(64),
            started_at   TIMESTAMP NOT NULL,
            last_seen    TIMESTAMP NOT NULL,
            role         VARCHAR(32) DEFAULT 'worker',
            version      VARCHAR(32),
            meta         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_last_seen
            ON homer_nodes(last_seen);
    """,
    "mysql": """
        CREATE TABLE IF NOT EXISTS homer_nodes (
            id           VARCHAR(64) PRIMARY KEY,
            hostname     VARCHAR(255) NOT NULL,
            ip           VARCHAR(64),
            started_at   DATETIME NOT NULL,
            last_seen    DATETIME NOT NULL,
            role         VARCHAR(32) DEFAULT 'worker',
            version      VARCHAR(32),
            meta         TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        CREATE INDEX idx_nodes_last_seen ON homer_nodes(last_seen);
    """,
    "oracle": """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_nodes (
                    id           VARCHAR2(64) PRIMARY KEY,
                    hostname     VARCHAR2(255) NOT NULL,
                    ip           VARCHAR2(64),
                    started_at   TIMESTAMP NOT NULL,
                    last_seen    TIMESTAMP NOT NULL,
                    role         VARCHAR2(32) DEFAULT ''worker'',
                    version      VARCHAR2(32),
                    meta         CLOB
                )';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
    """,
}


@dataclass
class Node:
    id: str
    hostname: str
    ip: Optional[str]
    started_at: datetime
    last_seen: datetime
    role: str
    version: Optional[str]
    meta: dict


class NodeRegistry:
    def __init__(self, config, node_id: Optional[str] = None,
                 role: str = "worker",
                 meta: Optional[dict] = None,
                 heartbeat_interval: int = 15,
                 ttl_seconds: int = 60):
        self.config = config
        self.node_id = node_id or str(uuid.uuid4())
        self.role = role
        self.meta = meta or {}
        self.heartbeat_interval = heartbeat_interval
        self.ttl_seconds = ttl_seconds

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.db = self._build_db()
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
        if ddl:
            if self._driver() == "oracle":
                cur = self.db.cursor()
                try: cur.execute(ddl)
                except Exception: pass
                finally:
                    try: cur.close()
                    except Exception: pass
            else:
                for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                    try: self.db.execute(stmt)
                    except Exception: pass
            self.db.commit()

    # ─────────── Public API ───────────

    def register(self):
        now = datetime.now()
        hostname = socket.gethostname()
        ip = _local_ip()
        import json

        existing = self._get()
        if existing:
            self.db.execute(
                f"UPDATE homer_nodes SET "
                f"hostname = {self._ph(0)}, ip = {self._ph(1)}, "
                f"last_seen = {self._ph(2)}, role = {self._ph(3)}, "
                f"version = {self._ph(4)}, meta = {self._ph(5)} "
                f"WHERE id = {self._ph(6)}",
                [hostname, ip, now, self.role,
                 self.config.get("app.version", ""),
                 json.dumps(self.meta, ensure_ascii=False),
                 self.node_id],
            )
        else:
            self.db.execute(
                f"INSERT INTO homer_nodes "
                f"(id, hostname, ip, started_at, last_seen, role, version, meta) "
                f"VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, "
                f"{self._ph(3)}, {self._ph(4)}, {self._ph(5)}, {self._ph(6)}, "
                f"{self._ph(7)})",
                [self.node_id, hostname, ip, now, now, self.role,
                 self.config.get("app.version", ""),
                 json.dumps(self.meta, ensure_ascii=False)],
            )
        self.db.commit()

    def unregister(self):
        self.db.execute(
            f"DELETE FROM homer_nodes WHERE id = {self._ph(0)}",
            [self.node_id],
        )
        self.db.commit()

    def start_heartbeat(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="homer-node-hb", daemon=True,
        )
        self._thread.start()

    def stop_heartbeat(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def list_nodes(self, only_alive: bool = True) -> list[Node]:
        """List registered nodes; stale nodes filtered if only_alive."""
        cutoff = datetime.now() - timedelta(seconds=self.ttl_seconds)
        if only_alive:
            sql = (
                f"SELECT * FROM homer_nodes WHERE last_seen > "
                f"{self._ph(0)} ORDER BY last_seen DESC"
            )
            rows = self.db.fetchall(sql, [cutoff], dictionary=True)
        else:
            rows = self.db.fetchall(
                "SELECT * FROM homer_nodes ORDER BY last_seen DESC",
                dictionary=True,
            )
        return [self._row(r) for r in rows]

    def purge_dead(self) -> int:
        """Remove nodes whose last_seen is older than TTL."""
        cutoff = datetime.now() - timedelta(seconds=self.ttl_seconds * 4)
        cur = self.db.execute(
            f"DELETE FROM homer_nodes WHERE last_seen < {self._ph(0)}",
            [cutoff],
        )
        self.db.commit()
        return cur.rowcount

    # ─────────── Internals ───────────

    def _get(self) -> Optional[Node]:
        row = self.db.fetchone(
            f"SELECT * FROM homer_nodes WHERE id = {self._ph(0)}",
            [self.node_id], dictionary=True,
        )
        return self._row(row) if row else None

    def _loop(self):
        while not self._stop.wait(self.heartbeat_interval):
            try:
                self._heartbeat()
                self.purge_dead()
            except Exception:
                pass

    def _heartbeat(self):
        self.db.execute(
            f"UPDATE homer_nodes SET last_seen = {self._ph(0)} "
            f"WHERE id = {self._ph(1)}",
            [datetime.now(), self.node_id],
        )
        self.db.commit()

    def _row(self, row) -> Node:
        import json
        d = dict(row) if not isinstance(row, dict) else row

        def _dt(v):
            if isinstance(v, datetime):
                return v
            if isinstance(v, str):
                try: return datetime.fromisoformat(v)
                except ValueError: pass
            return v

        meta = {}
        if d.get("meta"):
            try: meta = json.loads(d["meta"])
            except Exception: pass

        return Node(
            id=d["id"],
            hostname=d["hostname"],
            ip=d.get("ip"),
            started_at=_dt(d["started_at"]),
            last_seen=_dt(d["last_seen"]),
            role=d.get("role") or "worker",
            version=d.get("version"),
            meta=meta,
        )


def _local_ip() -> str:
    """Best-effort local IP (not 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
