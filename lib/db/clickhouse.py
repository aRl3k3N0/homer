"""
Драйвер ClickHouse.

Использует clickhouse-driver (native protocol) или clickhouse-connect (HTTP).
Приоритет — clickhouse-driver (быстрее).
"""
from __future__ import annotations

from .base import BaseDB, DBError


class ClickHouseDB(BaseDB):
    """ClickHouse."""

    driver_name = 'clickhouse'
    default_port = 9000
    _placeholder_style = '%s'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls) -> dict:
        return {
            'port': 9000,          # native protocol
            'http_port': 8123,     # HTTP (если protocol=http)
            'protocol': 'native',  # native | http
            'compression': 'lz4',
        }

    def _connect(self):
        protocol = (self.config.get('protocol') or 'native').lower()
        if protocol == 'http':
            return self._connect_http()
        return self._connect_native()

    def _connect_native(self):
        try:
            from clickhouse_driver import Client
        except ImportError as e:
            raise DBError(
                "Установите clickhouse-driver: pip install clickhouse-driver"
            ) from e

        cfg = self.config
        return Client(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 9000),
            user=cfg.get('user', 'default'),
            password=cfg.get('password', ''),
            database=cfg.get('database', 'default'),
            compression=cfg.get('compression', 'lz4'),
        )

    def _connect_http(self):
        try:
            import clickhouse_connect
        except ImportError as e:
            raise DBError(
                "Установите clickhouse-connect: pip install clickhouse-connect"
            ) from e

        cfg = self.config
        return clickhouse_connect.get_client(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('http_port', 8123),
            username=cfg.get('user', 'default'),
            password=cfg.get('password', ''),
            database=cfg.get('database', 'default'),
        )

    def _make_cursor(self, dictionary: bool = False):
        # У clickhouse-driver нет cursor — возвращаем сам клиент
        return self.connection

    # ─────────── Переопределяем выполнение под специфику CH ───────────

    def execute(self, sql, params=None, dictionary=False):
        # clickhouse-driver: client.execute() сразу возвращает данные
        self._last_result = self.connection.execute(sql, params or [])
        self._last_columns = getattr(self.connection, 'last_query', None)
        return self

    def fetchall(self, sql, params=None, dictionary=False):
        rows = self.connection.execute(sql, params or [], with_column_types=True)
        data, columns = rows
        if dictionary:
            col_names = [c[0] for c in columns]
            return [dict(zip(col_names, r)) for r in data]
        return data

    def fetchone(self, sql, params=None, dictionary=False):
        rows = self.fetchall(sql, params, dictionary=dictionary)
        return rows[0] if rows else None

    def fetchval(self, sql, params=None, default=None):
        rows = self.fetchall(sql, params)
        if not rows:
            return default
        row = rows[0]
        if isinstance(row, dict):
            return next(iter(row.values()))
        if isinstance(row, (list, tuple)):
            return row[0]
        return row

    def commit(self):
        # ClickHouse не требует commit — no-op
        pass

    def rollback(self):
        pass
