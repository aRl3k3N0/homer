"""
Публичный API i18n-подсистемы Homer.
"""
from .manager import (
    I18n,
    get_i18n,
    configure,
    set_locale,
    reset_locale,
    locale_ctx,
    t,
    tn,
)

__all__ = [
    'I18n',
    'get_i18n',
    'configure',
    'set_locale',
    'reset_locale',
    'locale_ctx',
    't',
    'tn',
]

def format_number(value, locale=None, **kwargs):
    return get_i18n().format_number(value, locale, **kwargs)

def format_percent(value, locale=None, **kwargs):
    return get_i18n().format_percent(value, locale, **kwargs)

def format_date(dt, locale=None, **kwargs):
    return get_i18n().format_date(dt, locale, **kwargs)

def format_datetime(dt, locale=None, **kwargs):
    return get_i18n().format_datetime(dt, locale, **kwargs)

def format_time(dt, locale=None, **kwargs):
    return get_i18n().format_time(dt, locale, **kwargs)
