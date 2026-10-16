"""
AuthManager — выбирает провайдера, выполняет аутентификацию,
управляет сессиями, проверяет права.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .store import AuthStore, User
from .providers import REGISTRY, AuthResult


class AuthManager:
    def __init__(self, config, store: AuthStore):
        self.config = config
        self.store = store
        self.providers = self._build_providers()

    # ─────────── Провайдеры ───────────

    def _build_providers(self):
        cfg = self.config.get('auth.providers', {}) or {}
        providers = {}

        # local всегда есть
        providers['local'] = REGISTRY['local'](self.config, self.store)

        for name in ('ldap', 'kerberos'):
            pc = cfg.get(name) or {}
            if not pc.get('enabled'):
                continue
            cls = REGISTRY.get(name)
            if not cls:
                continue
            try:
                providers[name] = cls(self.config)
            except Exception:
                continue
        return providers

    def provider(self, name: str):
        return self.providers.get(name)

    # ─────────── Аутентификация ───────────

    def authenticate(self, username: str, password: str,
                     *, ip: str = None, user_agent: str = None
                     ) -> Optional[tuple[User, str]]:
        """
        Возвращает (User, session_id) или None.
        Порядок: local → ldap (в порядке, в котором они в self.providers).
        """
        order = [n for n in ('local', 'ldap') if n in self.providers]
        for name in order:
            p = self.providers[name]
            try:
                result = p.authenticate(username, password)
            except Exception:
                continue
            if not result:
                continue
            user = self._sync_user(result)
            if not user or not user.enabled:
                continue
            sid = self.store.create_session(
                user.id, ip=ip, user_agent=user_agent,
            )
            return user, sid
        return None

    def authenticate_sso(self, request) -> Optional[tuple[User, str]]:
        """
        Аутентификация через SSO-заголовок (Kerberos).
        """
        p = self.providers.get('kerberos')
        if not p:
            return None
        try:
            result = p.authenticate_sso(request)
        except Exception:
            return None
        if not result:
            return None
        user = self._sync_user(result)
        if not user or not user.enabled:
            return None
        ip = getattr(request.client, 'host', None) if getattr(request, 'client', None) else None
        ua = request.headers.get('user-agent') if hasattr(request, 'headers') else None
        sid = self.store.create_session(user.id, ip=ip, user_agent=ua)
        return user, sid

    # ─────────── Сессии ───────────

    def user_by_session(self, sid: str) -> Optional[User]:
        return self.store.get_session(sid)

    def logout(self, sid: str):
        self.store.delete_session(sid)

    # ─────────── Синхронизация с БД ───────────

    def _sync_user(self, result: AuthResult) -> Optional[User]:
        """
        Гарантирует, что пользователь есть в БД Homer.
        - local: пользователь уже должен быть создан явно (admin/users:create)
        - ldap/kerberos: создаём/обновляем на лету
        """
        user = self.store.get_user_by_name(result.username)
        if result.provider == 'local':
            return user

        # Внешний провайдер
        if user is None:
            user = self.store.upsert_provider_user(
                result.username,
                provider=result.provider,
                display_name=result.display_name,
                email=result.email,
            )
            # Если роль пришла извне — назначим
            if result.roles:
                for role in result.roles:
                    if self.store.get_role(role):
                        self.store.assign_role(user.id, role)
            # Если ролей нет — назначим дефолтную
            if not self.store.roles_for_user(user.id):
                default = self.config.get(
                    f'auth.providers.{result.provider}.default_roles',
                    ['viewer'],
                ) or ['viewer']
                for role in default:
                    if self.store.get_role(role):
                        self.store.assign_role(user.id, role)
            return self.store.get_user(user.id)

        # Обновим атрибуты и роли
        self.store.upsert_provider_user(
            result.username,
            provider=result.provider,
            display_name=result.display_name,
            email=result.email,
        )
        if result.roles:
            current_roles = set(self.store.roles_for_user(user.id))
            desired = set(result.roles)
            for role in desired - current_roles:
                if self.store.get_role(role):
                    self.store.assign_role(user.id, role)
            for role in current_roles - desired:
                # Убираем роли, которых больше нет в LDAP (кроме вручную назначенных)
                if role in ('admin',):     # не снимаем встроенные
                    continue
                self.store.revoke_role(user.id, role)
        return self.store.get_user(user.id)

    def close(self):
        self.store.close()
