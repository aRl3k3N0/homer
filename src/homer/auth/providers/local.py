"""
Local-провайдер: пароли хранятся в БД Homer (pbkdf2-sha256).
"""
from .base import BaseProvider, AuthResult


class LocalProvider(BaseProvider):
    name = 'local'

    def __init__(self, config, store):
        super().__init__(config)
        self.store = store

    def authenticate(self, username, password):
        user = self.store.verify_credentials(username, password)
        if not user:
            return None
        return AuthResult(
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            roles=user.roles,
            provider='local',
        )
