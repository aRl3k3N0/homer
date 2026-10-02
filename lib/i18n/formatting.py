"""
Форматирование чисел и дат с учётом локали.

Если установлен babel — используется он (поддержка всех локалей).
Иначе — встроенные форматтеры для ru/en/de/fr.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union

try:
    from babel.numbers import format_decimal, format_percent as babel_pct
    from babel.dates import (
        format_date as babel_date,
        format_datetime as babel_datetime,
        format_time as babel_time,
    )
    _HAS_BABEL = True
except ImportError:
    _HAS_BABEL = False


# Простые правила для локалей без babel
_LOCALE_RULES = {
    'ru': {'sep': '\u00a0', 'dec': ',', 'date': '%d.%m.%Y', 'dt': '%d.%m.%Y %H:%M'},
    'uk': {'sep': '\u00a0', 'dec': ',', 'date': '%d.%m.%Y', 'dt': '%d.%m.%Y %H:%M'},
    'en': {'sep': ',', 'dec': '.', 'date': '%m/%d/%Y', 'dt': '%m/%d/%Y %I:%M %p'},
    'de': {'sep': '.', 'dec': ',', 'date': '%d.%m.%Y', 'dt': '%d.%m.%Y %H:%M'},
    'fr': {'sep': '\u202f', 'dec': ',', 'date': '%d/%m/%Y', 'dt': '%d/%m/%Y %H:%M'},
}
_DEFAULT_RULES = _LOCALE_RULES['en']


def _rules(locale: str) -> dict:
    return _LOCALE_RULES.get(locale[:2], _DEFAULT_RULES)


def format_number(
    value: Union[int, float, Decimal],
    locale: str = 'en',
    *,
    decimals: Optional[int] = None,
    grouping: bool = True,
) -> str:
    """
    format_number(1234567.89, 'ru') → '1 234 567,89'
    format_number(1234567.89, 'en') → '1,234,567.89'
    format_number(100, 'ru', decimals=2) → '100,00'
    """
    if _HAS_BABEL:
        try:
            pattern = None
            if decimals is not None:
                pattern = f'#,##0.{"0" * decimals}' if grouping else f'0.{"0" * decimals}'
            elif not grouping:
                pattern = '#0.###'
            return format_decimal(value, format=pattern, locale=locale)
        except Exception:
            pass

    # Fallback
    r = _rules(locale)
    if decimals is not None:
        s = f"{value:.{decimals}f}"
    else:
        s = str(value)
        if isinstance(value, float) and value.is_integer():
            s = str(int(value))

    int_part, _, frac_part = s.partition('.')
    if grouping and len(int_part) > 3:
        sign = ''
        if int_part.startswith('-'):
            sign, int_part = '-', int_part[1:]
        chunks = []
        while len(int_part) > 3:
            chunks.insert(0, int_part[-3:])
            int_part = int_part[:-3]
        chunks.insert(0, int_part)
        int_part = r['sep'].join(chunks)
        int_part = sign + int_part

    return int_part + (r['dec'] + frac_part if frac_part else '')


def format_percent(
    value: Union[int, float, Decimal],
    locale: str = 'en',
    *,
    decimals: int = 1,
) -> str:
    """0.1234 → '12,3%' (ru) | '12.3%' (en)"""
    if _HAS_BABEL:
        try:
            return babel_pct(value, locale=locale, decimal_quantization=True)
        except Exception:
            pass
    return format_number(value * 100, locale, decimals=decimals) + '%'


def format_date(dt: Union[date, datetime], locale: str = 'en',
                fmt: Optional[str] = None) -> str:
    """
    format_date(datetime(2026,10,2), 'ru') → '02.10.2026'
    """
    if _HAS_BABEL and fmt is None:
        try:
            return babel_date(dt, locale=locale)
        except Exception:
            pass
    r = _rules(locale)
    return dt.strftime(fmt or r['date'])


def format_datetime(dt: datetime, locale: str = 'en',
                    fmt: Optional[str] = None) -> str:
    if _HAS_BABEL and fmt is None:
        try:
            return babel_datetime(dt, locale=locale)
        except Exception:
            pass
    r = _rules(locale)
    return dt.strftime(fmt or r['dt'])


def format_time(dt: datetime, locale: str = 'en',
                fmt: Optional[str] = None) -> str:
    if _HAS_BABEL and fmt is None:
        try:
            return babel_time(dt, locale=locale)
        except Exception:
            pass
    return dt.strftime(fmt or '%H:%M')
