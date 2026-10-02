"""
Драйвер SQLite.
"""

from pathlib import Path
import sqlite3

from .base import BaseDB


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
