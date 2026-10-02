"""
LDAP / Active Directory провайдер.

Конфиг (config.yml):
    auth:
      providers:
        ldap:
          enabled: true
          server: "ldaps://dc.example.com:636"
          # либо несколько: ["ldap://dc1", "ldap://dc2"]
          use_tls: true
          bind_dn: "CN=homer,OU=Service,DC=example,DC=com"
          bind_password: "..."
          user_search_base: "OU=Users,DC=example,DC=com"
          user_filter: "(&(objectClass=user)(sAMAccountName={username}))"
          attr_username: "sAMAccountName"
          attr_display: "displayName"
          attr_email: "mail"
          # Маппинг групп AD → роли Homer
          group_role_map:
            "CN=HomerAdmins,OU=Groups,DC=example,DC=com": admin
            "CN=HomerOps,OU=Groups,DC=example,DC=com": operator
          default_roles: [viewer]
"""
from __future__ import annotations

import logging

from .base import BaseProvider, AuthResult


log = logging.getLogger('homer.auth.ldap')

try:
    import ldap3
    _HAS_LDAP = True
except ImportError:
    _HAS_LDAP = False


class LDAPProvider(BaseProvider):
    name = 'ldap'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('auth.providers.ldap', {}) or {}
        self.cfg = cfg
        self.enabled = cfg.get('enabled', False)
        self.server_uri = cfg.get('server', '')
        self.use_tls = cfg.get('use_tls', True)
        self.bind_dn = cfg.get('bind_dn')
        self.bind_password = cfg.get('bind_password')
        self.search_base = cfg.get('user_search_base', '')
        self.user_filter = cfg.get(
            'user_filter',
            '(&(objectClass=user)(sAMAccountName={username}))',
        )
        self.attr_username = cfg.get('attr_username', 'sAMAccountName')
        self.attr_display = cfg.get('attr_display', 'displayName')
        self.attr_email = cfg.get('attr_email', 'mail')
        self.group_role_map = cfg.get('group_role_map', {}) or {}
        self.default_roles = cfg.get('default_roles', ['viewer'])
        self.search_groups_base = cfg.get('group_search_base') or self.search_base

    # ─────────── Public ───────────

    def authenticate(self, username, password):
        if not self.enabled:
            return None
        if not _HAS_LDAP:
            log.error("ldap3 is not installed: pip install ldap3")
            return None
        if not password:
            return None

        server = ldap3.Server(self.server_uri, use_ssl=self.use_tls,
                              get_info=ldap3.NONE)
        try:
            # 1) Ищем DN пользователя через bind служебной учётки
            if self.bind_dn:
                conn = ldap3.Connection(
                    server, user=self.bind_dn, password=self.bind_password,
                    auto_bind=True,
                )
            else:
                # Анонимный bind для поиска
                conn = ldap3.Connection(server, auto_bind=True)

            try:
                flt = self.user_filter.format(username=ldap3.utils.conv.escape_filter_chars(username))
                conn.search(
                    search_base=self.search_base,
                    search_filter=flt,
                    attributes=[self.attr_username, self.attr_display,
                                self.attr_email, 'memberOf', 'distinguishedName'],
                )
                if not conn.entries:
                    return None
                entry = conn.entries[0]
                user_dn = entry.entry_dn
            finally:
                conn.unbind()

            # 2) Проверяем пароль — bind от DN пользователя
            uconn = ldap3.Connection(
                server, user=user_dn, password=password, auto_bind=False,
            )
            if not uconn.bind():
                return None
            uconn.unbind()

            # 3) Атрибуты
            attrs = entry.entry_attributes_as_dict
            uname = (attrs.get(self.attr_username) or [username])[0]
            display = (attrs.get(self.attr_display) or [uname])[0]
            email = (attrs.get(self.attr_email) or [''])[0]

            # 4) Роли
            member_of = attrs.get('memberOf') or []
            roles = self._map_roles(member_of)

            return AuthResult(
                username=uname, display_name=display, email=email,
                roles=roles, provider='ldap',
            )
        except ldap3.core.exceptions.LDAPException as e:
            log.warning(f"LDAP auth error: {e}")
            return None

    # ─────────── Private ───────────

    def _map_roles(self, groups):
        roles = set(self.default_roles)
        for group_dn in groups:
            dn_str = str(group_dn)
            for pattern, role in self.group_role_map.items():
                if pattern.lower() in dn_str.lower():
                    roles.add(role)
        return sorted(roles)
