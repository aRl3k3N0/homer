"""
Драйвер Oracle.
"""

from .base import BaseDB, DBError


class OracleDB(BaseDB):
    driver_name = 'oracle'
    default_port = 1521
    _placeholder_style = ':name'
    _supports_dict_cursor = True

    @classmethod
    def default_config(cls):
        return {'port': 1521}

    def _connect(self):
        try:
            import cx_Oracle
        except ImportError as e:
            raise DBError("Установите cx_Oracle для работы с Oracle") from e

        cfg = self.config
        dsn = cfg.get('dsn')
        if not dsn:
            service = cfg.get('service')
            sid = cfg.get('sid')
            dsn = cx_Oracle.makedsn(
                cfg.require('host'),
                cfg.get('port', 1521),
                service_name=service,
                sid=sid,
            )

        return cx_Oracle.connect(
            user=cfg.require('user'),
            password=cfg.require('password'),
            dsn=dsn,
        )

    def _make_cursor(self, dictionary=False):
        return self.connection.cursor()
