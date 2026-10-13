"""
History storage for the Web UI console.

Unified schema: every driver uses `user_name`. For legacy databases
created with SQLite's `user` column, init_schema() performs a one-time
migration (`ALTER TABLE ... RENAME COLUMN`).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from lib.db import connect, BaseDB, DBError

_log = logging.getLogger("homer.webui.history")


# ─────────── DDL (fresh installs) ───────────

DDL = {
    "sqlite": """
        CREATE TABLE IF NOT EXISTS homer_console_history (
            id           TEXT PRIMARY KEY,
            user_name    TEXT NOT NULL,
            command      TEXT NOT NULL,
            args_json    TEXT NOT NULL DEFAULT '{}',
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            exit_code    INTEGER,
            output       TEXT,
            input_log    TEXT,
            client_ip    TEXT,
            user_agent   TEXT,
            duration_ms  INTEGER,
            session_id   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_history_user
            ON homer_console_history(user_name);
        CREATE INDEX IF NOT EXISTS idx_history_command
            ON homer_console_history(command);
        CREATE INDEX IF NOT EXISTS idx_history_started_at
            ON homer_console_history(started_at DESC);
    """,
    "postgres": """
        CREATE TABLE IF NOT EXISTS homer_console_history (
            id           VARCHAR(36) PRIMARY KEY,
            user_name    VARCHAR(255) NOT NULL,
            command      VARCHAR(255) NOT NULL,
            args_json    TEXT NOT NULL DEFAULT '{}',
            started_at   TIMESTAMP NOT NULL,
            finished_at  TIMESTAMP,
            exit_code    INTEGER,
            output       TEXT,
            input_log    TEXT,
            client_ip    VARCHAR(64),
            user_agent   TEXT,
            duration_ms  INTEGER,
            session_id   VARCHAR(64)
        );
        CREATE INDEX IF NOT EXISTS idx_history_user
            ON homer_console_history(user_name);
        CREATE INDEX IF NOT EXISTS idx_history_command
            ON homer_console_history(command);
        CREATE INDEX IF NOT EXISTS idx_history_started_at
            ON homer_console_history(started_at DESC);
    """,
    "oracle": """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_console_history (
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
    """,
    "mysql": """
        CREATE TABLE IF NOT EXISTS homer_console_history (
            id           VARCHAR(36) PRIMARY KEY,
            user_name    VARCHAR(255) NOT NULL,
            command      VARCHAR(255) NOT NULL,
            args_json    TEXT NOT NULL,
            started_at   DATETIME NOT NULL,
            finished_at  DATETIME,
            exit_code    INT,
            output       LONGTEXT,
            input_log    LONGTEXT,
            client_ip    VARCHAR(64),
            user_agent   TEXT,
            duration_ms  INT,
            session_id   VARCHAR(64)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        CREATE INDEX idx_history_user
            ON homer_console_history(user_name);
        CREATE INDEX idx_history_command
            ON homer_console_history(command);
        CREATE INDEX idx_history_started_at
            ON homer_console_history(started_at DESC);
    """,
}


class HistoryStorage:
    MAX_OUTPUT_CHARS = 200_000

    def __init__(self, config, db: Optional[BaseDB] = None):
        self.config = config
        self._external_db = db is not None
        self.db = db or self._build_db()
        if not self.db.is_connected:
            self.db.connect()
        self.init_schema()

    # ─────────── DB ───────────

    def _build_db(self) -> BaseDB:
        sched_cfg = self.config.get("scheduler", {}) or {}
        driver = sched_cfg.get("storage", "sqlite")
        conn_cfg = sched_cfg.get(driver) or self.config.get(f"databases.{driver}")
        if driver == "sqlite":
            if not conn_cfg:
                conn_cfg = {"path": "var/cache/homer.db"}
            elif "path" not in conn_cfg:
                conn_cfg = dict(conn_cfg, path="var/cache/homer.db")
        return connect(driver, conn_cfg)

    def _driver(self) -> str:
        return self.db.driver_name

    def _ph(self, idx: int) -> str:
        style = self.db._placeholder_style
        if style == ":name":
            return f":{idx + 1}"
        if style == "?":
            return "?"
        return "%s"

    def _ph_list(self, n: int) -> str:
        return ", ".join(self._ph(i) for i in range(n))

    def _bool(self, v: bool):
        if self._driver() == "oracle":
            return 1 if v else 0
        return bool(v)

    # ─────────── Schema + migration ───────────

    def init_schema(self):
        driver = self._driver()

        # 1) Fresh schema (idempotent)
        ddl = DDL.get(driver)
        if ddl:
            if driver == "oracle":
                cur = self.db.cursor()
                try:
                    cur.execute(ddl)
                except Exception:
                    pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
            else:
                for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                    try:
                        self.db.execute(stmt)
                    except Exception:
                        pass
            self.db.commit()

        # 2) Legacy migration: `user` → `user_name`
        self._migrate_legacy_user_column()

    def _migrate_legacy_user_column(self):
        """
        Older SQLite databases used a `user` column. Rename it once.
        Uses PRAGMA table_info for SQLite; information_schema for
        Postgres; user_tab_columns for Oracle; SHOW COLUMNS for MySQL.
        """
        driver = self._driver()
        try:
            if driver == "sqlite":
                cols = self._sqlite_columns("homer_console_history")
                if "user_name" in cols:
                    return  # already migrated
                if "user" not in cols:
                    return  # nothing to migrate
                _log.info("history: migrating column user -> user_name")
                self.db.execute(
                    "ALTER TABLE homer_console_history "
                    "RENAME COLUMN user TO user_name"
                )
                self.db.commit()

            elif driver == "postgres":
                cols = self._pg_columns("homer_console_history")
                if "user_name" in cols:
                    return
                if "user" not in cols:
                    return
                _log.info("history: migrating column user -> user_name")
                self.db.execute(
                    "ALTER TABLE homer_console_history "
                    "RENAME COLUMN \"user\" TO user_name"
                )
                self.db.commit()

            elif driver == "mysql":
                cols = self._mysql_columns("homer_console_history")
                if "user_name" in cols:
                    return
                if "user" not in cols:
                    return
                _log.info("history: migrating column user -> user_name")
                self.db.execute(
                    "ALTER TABLE homer_console_history "
                    "CHANGE COLUMN `user` user_name VARCHAR(255) NOT NULL"
                )
                self.db.commit()

            elif driver == "oracle":
                cols = self._oracle_columns("HOMER_CONSOLE_HISTORY")
                if "USER_NAME" in cols:
                    return
                if "USER" not in cols:
                    return
                _log.info("history: migrating column user -> user_name")
                self.db.execute(
                    "ALTER TABLE homer_console_history "
                    "RENAME COLUMN \"USER\" TO user_name"
                )
                self.db.commit()
        except Exception as e:
            _log.warning("history: legacy column migration failed: %s", e)

    # ─────────── Introspection helpers ───────────

    def _sqlite_columns(self, table: str) -> set[str]:
        rows = self.db.fetchall(f"PRAGMA table_info({table})", dictionary=True)
        return {r["name"] for r in rows} if rows else set()

    def _pg_columns(self, table: str) -> set[str]:
        rows = self.db.fetchall(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = " + self._ph(0),
            [table], dictionary=True,
        )
        return {(r["column_name"] if isinstance(r, dict) else r[0]) for r in rows}

    def _mysql_columns(self, table: str) -> set[str]:
        rows = self.db.fetchall(f"SHOW COLUMNS FROM {table}", dictionary=True)
        return {(r["Field"] if isinstance(r, dict) else r[0]) for r in rows}

    def _oracle_columns(self, table: str) -> set[str]:
        rows = self.db.fetchall(
            "SELECT column_name FROM user_tab_columns "
            "WHERE table_name = " + self._ph(0),
            [table.upper()], dictionary=True,
        )
        return {(r["column_name"] if isinstance(r, dict) else r[0]).upper()
                for r in rows}

    # ─────────── CRUD (updated column name) ───────────

    def start(self, user: str, command: str, args: dict,
              client_ip: str | None = None,
              user_agent: str | None = None,
              session_id: str | None = None) -> str:
        entry_id = str(uuid.uuid4())
        now = datetime.now()
        cols = ("id, user_name, command, args_json, started_at, "
                "client_ip, user_agent, session_id")
        sql = (f"INSERT INTO homer_console_history ({cols}) "
               f"VALUES ({self._ph_list(8)})")
        self.db.execute(sql, [
            entry_id, user, command, json.dumps(args, ensure_ascii=False),
            now, client_ip, user_agent, session_id,
        ])
        self.db.commit()
        return entry_id

    def finish(self, entry_id: str, exit_code: int, output: str,
               input_log: list[str] | None = None):
        now = datetime.now()
        output = (output or "")[: self.MAX_OUTPUT_CHARS]

        row = self.db.fetchone(
            f"SELECT started_at FROM homer_console_history "
            f"WHERE id = {self._ph(0)}",
            [entry_id], dictionary=True,
        )
        started_at = None
        if row:
            started_at = row["started_at"] if isinstance(row, dict) else row[0]

        duration_ms = None
        if started_at:
            if isinstance(started_at, str):
                try:
                    started_at = datetime.fromisoformat(started_at)
                except ValueError:
                    try:
                        started_at = datetime.strptime(
                            started_at, "%Y-%m-%d %H:%M:%S"
                        )
                    except ValueError:
                        started_at = None
            if started_at:
                duration_ms = int((now - started_at).total_seconds() * 1000)

        input_log_json = None
        if input_log:
            input_log_json = json.dumps(input_log, ensure_ascii=False)

        sql = (
            f"UPDATE homer_console_history SET "
            f"  finished_at = {self._ph(0)}, "
            f"  exit_code = {self._ph(1)}, "
            f"  output = {self._ph(2)}, "
            f"  input_log = {self._ph(3)}, "
            f"  duration_ms = {self._ph(4)} "
            f"WHERE id = {self._ph(5)}"
        )
        self.db.execute(sql, [
            now, exit_code, output, input_log_json, duration_ms, entry_id,
        ])
        self.db.commit()

    def get(self, entry_id: str) -> Optional["HistoryEntry"]:
        row = self.db.fetchone(
            f"SELECT * FROM homer_console_history WHERE id = {self._ph(0)}",
            [entry_id], dictionary=True,
        )
        return self._row_to_entry(row) if row else None

    def list(self, user: str | None = None,
             command: str | None = None,
             limit: int = 100,
             offset: int = 0) -> list["HistoryEntry"]:
        where = []
        params: list[Any] = []
        if user:
            where.append(f"user_name = {self._ph(len(params))}")
            params.append(user)
        if command:
            where.append(f"command = {self._ph(len(params))}")
            params.append(command)
        where_sql = "WHERE " + " AND ".join(where) if where else ""

        sql = (
            f"SELECT * FROM homer_console_history {where_sql} "
            f"ORDER BY started_at DESC "
            f"LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        rows = self.db.fetchall(sql, params or None, dictionary=True)
        return [self._row_to_entry(r) for r in rows]

    def distinct_commands(self, user: str | None = None) -> list[str]:
        if user:
            sql = (
                f"SELECT DISTINCT command FROM homer_console_history "
                f"WHERE user_name = {self._ph(0)} ORDER BY command"
            )
            rows = self.db.fetchall(sql, [user], dictionary=True)
        else:
            rows = self.db.fetchall(
                "SELECT DISTINCT command FROM homer_console_history "
                "ORDER BY command",
                dictionary=True,
            )
        return [(r["command"] if isinstance(r, dict) else r[0]) for r in rows]

    def purge_older_than(self, seconds: int) -> int:
        cutoff = datetime.now() - timedelta(seconds=seconds)
        cur = self.db.execute(
            f"DELETE FROM homer_console_history "
            f"WHERE started_at < {self._ph(0)}",
            [cutoff],
        )
        self.db.commit()
        return cur.rowcount

    def close(self):
        if not self._external_db:
            self.db.close()

    # lib/webui/history.py — метод HistoryStorage

    def distinct_users(self) -> list[str]:
        """
        Return all distinct users present in homer_console_history.
        """
        rows = self.db.fetchall(
            "SELECT DISTINCT user_name FROM homer_console_history "
            "ORDER BY user_name",
            dictionary=True,
        )
        return [
            (r["user_name"] if isinstance(r, dict) else r[0])
            for r in rows
            if (r["user_name"] if isinstance(r, dict) else r[0])
        ]

    # ─────────── Row → HistoryEntry ───────────

    def _row_to_entry(self, row) -> "HistoryEntry":
        d = dict(row) if not isinstance(row, dict) else row

        args_raw = d.get("args_json") or "{}"
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {}

        input_log_raw = d.get("input_log")
        input_log = []
        if input_log_raw:
            try:
                input_log = json.loads(input_log_raw)
            except Exception:
                pass

        def _dt(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v))
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(str(v), fmt)
                    except ValueError:
                        continue
            return None

        # Accept both legacy and new column names when reading.
        user_value = d.get("user_name")
        if user_value is None:
            user_value = d.get("user") or "anonymous"

        return HistoryEntry(
            id=d.get("id"),
            user=user_value,
            command=d.get("command") or "",
            args=args,
            started_at=_dt(d.get("started_at")),
            finished_at=_dt(d.get("finished_at")),
            exit_code=d.get("exit_code"),
            output=d.get("output"),
            input_log=input_log,
            client_ip=d.get("client_ip"),
            user_agent=d.get("user_agent"),
            duration_ms=d.get("duration_ms"),
            session_id=d.get("session_id"),
        )


@dataclass
class HistoryEntry:
    id: str
    user: str
    command: str
    args: dict[str, Any]
    started_at: datetime
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    output: Optional[str] = None
    input_log: list[str] = field(default_factory=list)
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    duration_ms: Optional[int] = None
    session_id: Optional[str] = None
