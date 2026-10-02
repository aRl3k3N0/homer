"""
Базовый класс для всех драйверов БД.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, Optional

from lib.tracing import span


class DBError(Exception):
    """Общая ошибка уровня БД Homer"""


class ConnectionConfig:
    """
    Универсальный контейнер параметров подключения.
    """

    def __init__(self, data: Optional[dict] = None, **kwargs):
        self._data = {}
        if data:
            self._data.update(data)
        self._data.update(kwargs)

    @classmethod
    def from_config(cls, config, prefix=None, defaults=None):
        data = dict(defaults or {})
        if prefix:
            section = config.get(prefix) or {}
            if isinstance(section, dict):
                data.update(section)
        return cls(data)

    @classmethod
    def from_any(cls, source, prefix=None, defaults=None):
        if source is None:
            return cls(defaults or {})
        if isinstance(source, ConnectionConfig):
            return source
        if isinstance(source, dict):
            data = dict(defaults or {})
            data.update(source)
            return cls(data)
        return cls.from_config(source, prefix, defaults)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def require(self, key):
        if key not in self._data or self._data[key] is None:
            raise DBError(f"Отсутствует обязательный параметр подключения: '{key}'")
        return self._data[key]

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def as_dict(self):
        return dict(self._data)

    def __repr__(self):
        safe = {k: ('***' if 'pass' in k.lower() else v) for k, v in self._data.items()}
        return f"ConnectionConfig({safe})"


class BaseDB:
    driver_name = 'base'
    default_port = None
    _placeholder_style = '%s'
    _supports_dict_cursor = False

    def __init__(self, connection=None, *, connect=True, autocommit=False):
        self._connection_cfg = self._normalize_config(connection)
        self._conn = None
        self._autocommit = autocommit
        if connect:
            self.connect()

    @classmethod
    def _normalize_config(cls, source):
        return ConnectionConfig.from_any(
            source,
            prefix=None,
            defaults=cls.default_config(),
        )

    @classmethod
    def default_config(cls):
        return {}

    @property
    def config(self):
        return self._connection_cfg

    def connect(self):
        if self._conn is not None:
            return self
        self._conn = self._connect()
        return self

    def close(self):
        if self._conn is None:
            return
        try:
            self._close_impl()
        finally:
            self._conn = None

    @property
    def connection(self):
        if self._conn is None:
            raise DBError(f"[{self.driver_name}] Нет активного соединения. Вызовите .connect()")
        return self._conn

    @property
    def is_connected(self):
        return self._conn is not None

    def cursor(self, dictionary=False):
        return self._make_cursor(dictionary=dictionary)

    def execute(
        self, sql: str, params: Optional[Sequence[Any]] = None, dictionary: bool = False
    ) -> Any:
        from lib.metrics import inc_db_query

        inc_db_query(self.driver_name, 'execute')

        with span(
            f'db.{self.driver_name}.execute',
            kind='client',
            attributes={
                'db.system': self.driver_name,
                'db.statement': sql[:200],
                'db.operation': sql.strip().split(maxsplit=1)[0].upper()[:20],
            },
        ):
            cur = self.cursor(dictionary=dictionary)
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            return cur

    def executemany(self, sql, seq_params, dictionary=False):
        cur = self.cursor(dictionary=dictionary)
        cur.executemany(sql, seq_params)
        return cur

    def fetchall(
        self, sql: str, params: Optional[Sequence[Any]] = None, dictionary: bool = False
    ) -> list[Any]:
        cur = self.execute(sql, params, dictionary=dictionary)
        return cur.fetchall()

    def fetchone(
        self, sql: str, params: Optional[Sequence[Any]] = None, dictionary: bool = False
    ) -> Optional[Any]:
        cur = self.execute(sql, params, dictionary=dictionary)
        return cur.fetchone()

    def fetchval(
        self, sql: str, params: Optional[Sequence[Any]] = None, default: Any = None
    ) -> Any:
        row = self.fetchone(sql, params)
        if row is None:
            return default
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def scalar(self, sql, params=None, default=None):
        return self.fetchval(sql, params, default)

    def commit(self):
        if self._conn is not None and hasattr(self._conn, 'commit'):
            self._conn.commit()

    def rollback(self):
        if self._conn is not None and hasattr(self._conn, 'rollback'):
            self._conn.rollback()

    @contextmanager
    def transaction(self):
        try:
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise

    def __enter__(self):
        if not self.is_connected:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def placeholder(cls, index):
        if cls._placeholder_style == '%s':
            return '%s'
        if cls._placeholder_style == '?':
            return '?'
        if cls._placeholder_style == ':name':
            return f':{index + 1}'
        return '%s'

    def _connect(self):
        raise NotImplementedError

    def _close_impl(self):
        if self._conn is not None and hasattr(self._conn, 'close'):
            self._conn.close()

    def _make_cursor(self, dictionary=False):
        raise NotImplementedError

    def __getattr__(self, item):
        conn = self.__dict__.get('_conn')
        if conn is not None and hasattr(conn, item):
            return getattr(conn, item)
        raise AttributeError(item)
