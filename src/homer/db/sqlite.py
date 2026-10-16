"""
Драйвер SQLite.
"""

from pathlib import Path
import sqlite3
from datetime import datetime
from .base import BaseDB

_SQLITE_DT_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

def _adapt_datetime(dt: datetime) -> str:
    """Python datetime -> SQLite TEXT."""
    return dt.strftime(_SQLITE_DT_FORMAT)


def _convert_timestamp(raw: bytes) -> datetime:
    """SQLite TEXT -> Python datetime."""
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    if not text:
        raise ValueError("empty timestamp")
    try:
        return datetime.strptime(text, _SQLITE_DT_FORMAT)
    except ValueError:
        pass
    # Fallback: ISO 8601 или без микросекунд
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def _register_sqlite_adapters():
    """Идемпотентная регистрация адаптеров."""
    if getattr(_register_sqlite_adapters, "_done", False):
        return
    sqlite3.register_adapter(datetime, _adapt_datetime)
    sqlite3.register_converter("TIMESTAMP", _convert_timestamp)
    sqlite3.register_converter("DATETIME", _convert_timestamp)
    _register_sqlite_adapters._done = True

class SQLiteDB(BaseDB):
    driver_name = 'sqlite'
    default_port = None
    _placeholder_style = '?'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls):
        return {'timeout': 5}

    def _connect(self):
        cfg = self.config
        path = cfg.require('path')
        parent = Path(path).parent
        if parent and str(parent) not in ('', '.'):
            parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(path),
            timeout=cfg.get('timeout', 5),
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _make_cursor(self, dictionary=False):
        return self.connection.cursor()

    def fetchall(self, sql, params=None, dictionary=False):
        rows = super().fetchall(sql, params, dictionary=False)
        if dictionary:
            return [dict(r) for r in rows]
        return rows

    def fetchone(self, sql, params=None, dictionary=False):
        row = super().fetchone(sql, params, dictionary=False)
        if row is None:
            return None
        if dictionary:
            return dict(row)
        return row

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        _register_sqlite_adapters()

        conn = sqlite3.connect(
            self._path,
            timeout=self._timeout,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass
        self._local.conn = conn
        return conn
