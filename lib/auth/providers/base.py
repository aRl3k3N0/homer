"""
Интерфейс провайдера авторизации.

Провайдер отвечает за:
    - аутентификацию (username/password ИЛИ уже-принятую идентичность)
    - возврат данных пользователя (username, display_name, email, roles)
Ядро Homer выполняет авторизацию (сопоставление ролей/прав) — у нас одна
модель ролей для всех провайдеров.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AuthResult:
    username: str
    display_name: str = ''
    email: str = ''
    roles: list[str] = None     # роли из внешнего источника (могут быть пустыми)
    provider: str = ''
    raw: dict = None            # исходные атрибуты для логов/отладки


class BaseProvider:
    name = 'base'

    def __init__(self, config: dict):
        self.config = config

    def authenticate(self, username: str, password: str) -> Optional[AuthResult]:
        raise NotImplementedError

    def authenticate_sso(self, request=None) -> Optional[AuthResult]:
        """
        Аутентификация без пароля (через headers/токены/cookie).
        Например, Kerberos/SSO-заголовки от reverse proxy.
        """
        return None
