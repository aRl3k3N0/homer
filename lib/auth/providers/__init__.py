from .base import BaseProvider, AuthResult
from .local import LocalProvider
from .ldap import LDAPProvider
from .kerberos import KerberosProvider

REGISTRY = {
    'local': LocalProvider,
    'ldap': LDAPProvider,
    'kerberos': KerberosProvider,
}

__all__ = ['BaseProvider', 'AuthResult', 'LocalProvider',
           'LDAPProvider', 'KerberosProvider', 'REGISTRY']
