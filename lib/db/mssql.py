"""
Драйвер Microsoft SQL Server.

Поддерживает два варианта подключения:
    - pyodbc (ODBC Driver 17/18)
    - pymssql (FreeTDS)
Приоритет — pyodbc.

Конфиг:
    driver: 'ODBC Driver 18 for SQL Server'
    server: 'host,1433' | host
    database: 'db'
    user / password       — SQL-аутентификация
    trusted_connection    — Windows-аутентификация (True/False)
    encrypt: yes|no|strict
    trust_server_certificate: yes|no
"""

from __future__ import annotations

from .base import BaseDB, DBError


class MSSQLDB(BaseDB):
    """MS SQL Server."""

    driver_name = 'mssql'
    default_port = 1433
    _placeholder_style = '?'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls) -> dict:
        return {
            'port': 1433,
            'driver': 'ODBC Driver 18 for SQL Server',
            'encrypt': 'yes',
            'trust_server_certificate': 'yes',
        }

    def _connect(self):
        # Пробуем pyodbc
        try:
            import pyodbc
        except ImportError:
            return self._connect_pymssql()

        cfg = self.config
        driver = cfg.get('driver', 'ODBC Driver 18 for SQL Server')
        host = cfg.require('host')
        port = cfg.get('port', 1433)
        database = cfg.require('database')

        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={host},{port}",
            f"DATABASE={database}",
            f"Encrypt={cfg.get('encrypt', 'yes')}",
            f"TrustServerCertificate={cfg.get('trust_server_certificate', 'yes')}",
        ]

        if cfg.get('trusted_connection'):
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={cfg.require('user')}")
            parts.append(f"PWD={cfg.get('password', '')}")

        conn_str = ';'.join(parts)
        try:
            return pyodbc.connect(
                conn_str, autocommit=False, timeout=cfg.get('connect_timeout', 10)
            )
        except Exception as e:
            raise DBError(f"MS SQL (pyodbc) ошибка подключения: {e}") from e

    def _connect_pymssql(self):
        try:
            import pymssql
        except ImportError as e:
            raise DBError(
                "Установите pyodbc (рекомендуется) или pymssql для MS SQL: pip install pyodbc"
            ) from e

        cfg = self.config
        return pymssql.connect(
            server=cfg.require('host'),
            port=cfg.get('port', 1433),
            user=cfg.require('user'),
            password=cfg.get('password', ''),
            database=cfg.require('database'),
            timeout=cfg.get('connect_timeout', 10),
            as_dict=True,
        )

    def _make_cursor(self, dictionary: bool = False):
        return self.connection.cursor()

    def fetchall(self, sql, params=None, dictionary=False):
        rows = super().fetchall(sql, params, dictionary=False)
        if dictionary and rows and not isinstance(rows[0], dict):
            # pyodbc.Row → dict через cursor.description
            cur = self.cursor()
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in rows]
        return rows

    def fetchone(self, sql, params=None, dictionary=False):
        row = super().fetchone(sql, params, dictionary=False)
        if row is None:
            return None
        if dictionary and not isinstance(row, dict):
            cur = self.cursor()
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        return row
