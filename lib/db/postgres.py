"""
Драйвер PostgreSQL.
"""

from .base import BaseDB, DBError


class PostgresDB(BaseDB):
    driver_name = 'postgres'
    default_port = 5432
    _placeholder_style = '%s'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls):
        return {'port': 5432}

    def _connect(self):
        try:
            import psycopg2
        except ImportError as e:
            raise DBError("Установите psycopg2-binary для работы с PostgreSQL") from e

        cfg = self.config
        dsn = cfg.get('dsn')
        if dsn:
            return psycopg2.connect(dsn)

        database = cfg.get('database') or cfg.get('dbname')
        if not database:
            raise DBError("Не указан database (или dbname) для PostgreSQL")

        kwargs = {
            'host': cfg.get('host', 'localhost'),
            'port': cfg.get('port', 5432),
            'dbname': database,
            'user': cfg.require('user'),
            'password': cfg.require('password'),
        }
        if cfg.get('sslmode'):
            kwargs['sslmode'] = cfg['sslmode']
        if cfg.get('connect_timeout'):
            kwargs['connect_timeout'] = cfg['connect_timeout']

        return psycopg2.connect(**kwargs)

    def _make_cursor(self, dictionary=False):
        if dictionary:
            from psycopg2.extras import RealDictCursor

            return self.connection.cursor(cursor_factory=RealDictCursor)
        return self.connection.cursor()
