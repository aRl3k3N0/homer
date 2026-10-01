"""
MongoDB — документная БД.

Особенности:
    - Нет SQL. Работаем через коллекции.
    - Даём удобный API: db.collection('users').find({...}).
"""
from __future__ import annotations

from .base import BaseDB, DBError


class MongoDB(BaseDB):
    """MongoDB через pymongo."""

    driver_name = 'mongo'
    default_port = 27017
    _placeholder_style = '%s'

    @classmethod
    def default_config(cls) -> dict:
        return {
            'port': 27017,
            'auth_source': 'admin',
            'server_selection_timeout_ms': 5000,
        }

    def _connect(self):
        try:
            from pymongo import MongoClient
        except ImportError as e:
            raise DBError(
                "Установите pymongo: pip install pymongo"
            ) from e

        cfg = self.config

        if cfg.get('uri'):
            client = MongoClient(
                cfg['uri'],
                serverSelectionTimeoutMS=cfg.get('server_selection_timeout_ms', 5000),
            )
        else:
            client = MongoClient(
                host=cfg.get('host', 'localhost'),
                port=cfg.get('port', 27017),
                username=cfg.get('user') or cfg.get('username'),
                password=cfg.get('password'),
                authSource=cfg.get('auth_source', 'admin'),
                serverSelectionTimeoutMS=cfg.get('server_selection_timeout_ms', 5000),
            )

        # Проверка связи
        try:
            client.admin.command('ping')
        except Exception as e:
            raise DBError(f"MongoDB ошибка подключения: {e}") from e

        return client

    def _make_cursor(self, dictionary=False):
        return self.connection

    # ─────────── SQL-интерфейс не поддерживается ───────────

    def execute(self, *_, **__):
        raise DBError(
            "MongoDB не поддерживает SQL. Используйте .db('name').collection('x') "
            "или .client.<database>."
        )

    # ─────────── Удобные обёртки ───────────

    @property
    def client(self):
        """Нативный pymongo.MongoClient."""
        return self.connection

    def db(self, name: str | None = None):
        """Получить базу (по умолчанию — из конфига)."""
        name = name or self.config.get('database')
        if not name:
            raise DBError("Не указано имя базы (database)")
        return self.client[name]

    def collection(self, name: str, database: str | None = None):
        """Получить коллекцию."""
        return self.db(database)[name]

    def ping(self):
        return self.client.admin.command('ping')

    def list_databases(self):
        return self.client.list_database_names()

    def list_collections(self, database: str | None = None):
        return self.db(database).list_collection_names()
