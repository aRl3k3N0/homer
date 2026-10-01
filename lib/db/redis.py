"""
Redis — key-value store.

Особенности:
    - Нет SQL. Интерфейс BaseDB частично не применим.
    - Даём доступ к нативному клиенту через .client / делегирование.
    - Работает как кэш, очередь, pub/sub.
"""
from __future__ import annotations

from .base import BaseDB, DBError


class RedisDB(BaseDB):
    """Redis через redis-py."""

    driver_name = 'redis'
    default_port = 6379
    _placeholder_style = '%s'

    @classmethod
    def default_config(cls) -> dict:
        return {
            'port': 6379,
            'db': 0,
            'decode_responses': True,
            'socket_timeout': 10,
            'health_check_interval': 30,
        }

    def _connect(self):
        try:
            import redis
        except ImportError as e:
            raise DBError(
                "Установите redis: pip install redis"
            ) from e

        cfg = self.config

        if cfg.get('url'):
            return redis.from_url(
                cfg['url'],
                decode_responses=cfg.get('decode_responses', True),
                socket_timeout=cfg.get('socket_timeout', 10),
                health_check_interval=cfg.get('health_check_interval', 30),
            )

        return redis.Redis(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 6379),
            db=cfg.get('db', 0),
            password=cfg.get('password'),
            username=cfg.get('username'),
            ssl=cfg.get('ssl', False),
            decode_responses=cfg.get('decode_responses', True),
            socket_timeout=cfg.get('socket_timeout', 10),
            health_check_interval=cfg.get('health_check_interval', 30),
        )

    def _make_cursor(self, dictionary=False):
        return self.connection

    # ─────────── SQL-интерфейс не поддерживается ───────────

    def execute(self, *_, **__):
        raise DBError(
            "Redis не поддерживает SQL. Используйте .client.<метод> "
            "(например, db.client.get('key'))."
        )

    # ─────────── Удобные обёртки ───────────

    @property
    def client(self):
        """Нативный redis.Redis клиент."""
        return self.connection

    def get(self, key, default=None):
        v = self.client.get(key)
        return v if v is not None else default

    def set(self, key, value, ex=None):
        return self.client.set(key, value, ex=ex)

    def delete(self, *keys):
        return self.client.delete(*keys)

    def exists(self, key):
        return bool(self.client.exists(key))

    def hgetall(self, name):
        return self.client.hgetall(name)

    def hset(self, name, key=None, value=None, mapping=None):
        return self.client.hset(name, key=key, value=value, mapping=mapping)

    def publish(self, channel, message):
        return self.client.publish(channel, message)

    def ping(self):
        return self.client.ping()
