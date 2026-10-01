"""
Драйверы и утилиты для работы с БД.
"""
from .base import BaseDB, ConnectionConfig, DBError
from .oracle import OracleDB
from .postgres import PostgresDB
from .sqlite import SQLiteDB
from .mysql import MySQLDB, MariaDBDB
from .mssql import MSSQLDB
from .clickhouse import ClickHouseDB
from .redis import RedisDB
from .mongo import MongoDB


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
        raise DBError(
            f"Неизвестный драйвер БД: '{name}'. "
            f"Доступные: {', '.join(sorted(DRIVERS))}"
        )
    return DRIVERS[key]


def connect(driver, connection=None, **kwargs):
    if isinstance(driver, type) and issubclass(driver, BaseDB):
        return driver(connection, **kwargs)
    cls = get_driver(driver)
    return cls(connection, **kwargs)


__all__ = [
    'BaseDB', 'ConnectionConfig', 'DBError',
    'OracleDB', 'PostgresDB', 'SQLiteDB',
    'MySQLDB', 'MariaDBDB', 'MSSQLDB', 'ClickHouseDB',
    'RedisDB', 'MongoDB',
    'DRIVERS', 'get_driver', 'connect',
]
