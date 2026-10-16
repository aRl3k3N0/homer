"""
Kerberos / SSO / Windows Integrated Authentication.

Два режима:

  A) Через reverse proxy (Apache/nginx + mod_auth_kerb/SPNEGO):
     RP делает SSO, прокидывает заголовок REMOTE_USER или X-Remote-User.
     Homer доверяет заголовку, если запрос с доверенного IP.
     Это рекомендуемый вариант — работает без ввода пароля у Windows-клиента.

  B) Напрямую через GSSAPI (в Python): требует pyspnego/gssapi,
     библиотек Kerberos и keytab'а. Реализуем через `pyspnego`.

Конфиг:
    auth:
      providers:
        kerberos:
          enabled: true
          mode: proxy             # proxy | gssapi
          trusted_proxies:
            - 10.0.0.0/8
            - 127.0.0.1
          header: X-Remote-User   # для proxy-режима
          # Для gssapi:
          keytab: /etc/homer/homer.keytab
          service: HTTP/homer.example.com
          realm: EXAMPLE.COM
          default_roles: [viewer]
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Optional

from .base import BaseProvider, AuthResult


log = logging.getLogger('homer.auth.kerberos')


class KerberosProvider(BaseProvider):
    name = 'kerberos'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('auth.providers.kerberos', {}) or {}
        self.cfg = cfg
        self.enabled = cfg.get('enabled', False)
        self.mode = cfg.get('mode', 'proxy')
        self.header = cfg.get('header', 'X-Remote-User')
        self.trusted_proxies = self._parse_networks(
            cfg.get('trusted_proxies') or ['127.0.0.1/32', '::1/128']
        )
        self.default_roles = cfg.get('default_roles', ['viewer'])
        self.realm = cfg.get('realm', '')
        self.service = cfg.get('service', '')
        self.keytab = cfg.get('keytab')

    # ─────────── Public ───────────

    def authenticate(self, username, password):
        # Kerberos не использует явный пароль — этот метод не применим
        return None

    def authenticate_sso(self, request=None) -> Optional[AuthResult]:
        if not self.enabled or request is None:
            return None

        if self.mode == 'proxy':
            return self._auth_proxy(request)
        if self.mode == 'gssapi':
            return self._auth_gssapi(request)
        return None

    # ─────────── Proxy ───────────

    def _auth_proxy(self, request):
        # Проверяем, что запрос пришёл от доверенного прокси
        client_ip = None
        try:
            client_ip = request.client.host if request.client else None
        except Exception:
            pass
        if not self._is_trusted(client_ip):
            log.warning(f"Kerberos proxy: untrusted IP {client_ip}")
            return None

        raw = request.headers.get(self.header) or ''
        if not raw:
            return None

        # Может быть 'DOMAIN\\user' или 'user@REALM'
        username = raw.split('\\')[-1].split('@')[0].strip()
        if not username:
            return None

        return AuthResult(
            username=username.lower(),
            display_name=username,
            email='',
            roles=list(self.default_roles),
            provider='kerberos',
            raw={'remote_user': raw},
        )

    # ─────────── GSSAPI ───────────

    def _auth_gssapi(self, request):
        # Извлекаем Negotiate-токен и валидируем через pyspnego
        try:
            import pyspnego
        except ImportError:
            log.error("pyspnego is not installed: pip install pyspnego")
            return None

        header = request.headers.get('Authorization', '')
        if not header.lower().startswith('negotiate '):
            return None
        token_b64 = header.split(' ', 1)[1].strip()
        import base64
        try:
            token = base64.b64decode(token_b64)
        except Exception:
            return None

        try:
            ctx = pyspnego.server()
            result = ctx.step(token)
            username = result.client_principal or ''
            username = username.split('@')[0].split('\\')[-1].lower()
            if not username:
                return None
            return AuthResult(
                username=username,
                display_name=username,
                email='',
                roles=list(self.default_roles),
                provider='kerberos',
            )
        except Exception as e:
            log.warning(f"GSSAPI: {e}")
            return None

    # ─────────── Private ───────────

    @staticmethod
    def _parse_networks(items):
        result = []
        for it in items:
            try:
                result.append(ipaddress.ip_network(it, strict=False))
            except ValueError:
                continue
        return result

    def _is_trusted(self, ip: str | None) -> bool:
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.trusted_proxies)
