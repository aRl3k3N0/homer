"""
Драйверы и утилиты для работы с БД.
"""

from .base import BaseDB, ConnectionConfig, DBError
from .clickhouse import ClickHouseDB
from .mongo import MongoDB
from .mssql import MSSQLDB
from .mysql import MariaDBDB, MySQLDB
from .oracle import OracleDB
from .postgres import PostgresDB
from .redis import RedisDB
from .sqlite import SQLiteDB

DRIVERS = {
    # Реляционные
    'oracle': OracleDB,
    'postgres': PostgresDB,
    'postgresql': PostgresDB,
    'sqlite': SQLiteDB,
    'mysql': MySQLDB,
    'mariadb': MariaDBDB,
    'mssql': MSSQLDB,
    'sqlserver': MSSQLDB,
    # Аналитические
    'clickhouse': ClickHouseDB,
    # NoSQL / KV
    'redis': RedisDB,
    'mongo': MongoDB,
    'mongodb': MongoDB,
}


def get_driver(name: str):
    key = name.lower()
    if key not in DRIVERS:
        raise DBError(f"Неизвестный драйвер БД: '{name}'. Доступные: {', '.join(sorted(DRIVERS))}")
    return DRIVERS[key]


def connect(driver, connection=None, **kwargs):
    if isinstance(driver, type) and issubclass(driver, BaseDB):
        return driver(connection, **kwargs)
    cls = get_driver(driver)
    return cls(connection, **kwargs)


__all__ = [
    'DRIVERS',
    'MSSQLDB',
    'BaseDB',
    'ClickHouseDB',
    'ConnectionConfig',
    'DBError',
    'MariaDBDB',
    'MongoDB',
    'MySQLDB',
    'OracleDB',
    'PostgresDB',
    'RedisDB',
    'SQLiteDB',
    'connect',
    'get_driver',
]
