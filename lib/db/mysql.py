"""
Драйвер MySQL / MariaDB.

Устанавливает pymysql или mysql-connector-python.
Приоритет — pymysql (чистый Python, без сборки).
"""
from __future__ import annotations

from .base import BaseDB, DBError


class MySQLDB(BaseDB):
    """MySQL / MariaDB через pymysql."""

    driver_name = 'mysql'
    default_port = 3306
    _placeholder_style = '%s'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls) -> dict:
        return {
            'port': 3306,
            'charset': 'utf8mb4',
            'autocommit': False,
            'connect_timeout': 10,
        }

    def _connect(self):
        try:
            import pymysql
        except ImportError as e:
            raise DBError(
                "Установите pymysql для работы с MySQL/MariaDB: "
                "pip install pymysql"
            ) from e

        cfg = self.config
        return pymysql.connect(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 3306),
            user=cfg.require('user'),
            password=cfg.get('password', ''),
            database=cfg.get('database') or cfg.get('dbname'),
            charset=cfg.get('charset', 'utf8mb4'),
            autocommit=cfg.get('autocommit', False),
            connect_timeout=cfg.get('connect_timeout', 10),
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _make_cursor(self, dictionary: bool = False):
        import pymysql.cursors
        # У нас соединение всегда с DictCursor — используем его
        return self.connection.cursor()


# MariaDB — тот же драйвер, отдельный алиас
MariaDBDB = MySQLDB
