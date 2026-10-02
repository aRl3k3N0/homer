"""Utilities for splitting SQL migration files into executable statements."""

from __future__ import annotations

import re

_DRIVER_ALIASES = {
    'postgresql': 'postgres',
    'mariadb': 'mysql',
}
_DOLLAR_QUOTE = re.compile(r'\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$')
_ORACLE_PLSQL = re.compile(
    r'^\s*(?:DECLARE\b|BEGIN\b|CREATE\s+(?:OR\s+REPLACE\s+)?'
    r'(?:(?:NON)?EDITIONABLE\s+)?(?:PROCEDURE|FUNCTION|TRIGGER|PACKAGE|TYPE)\b)',
    re.IGNORECASE,
)


def normalize_driver(driver: str) -> str:
    """Return the canonical SQL dialect name for a supported driver alias."""
    return _DRIVER_ALIASES.get(driver.lower(), driver.lower())


def _is_oracle_plsql(statement: str) -> bool:
    return bool(_ORACLE_PLSQL.match(statement))


def split_sql(text: str, driver: str) -> list[str]:
    """Split SQL at statement delimiters without splitting quoted text.

    Supports SQL comments, escaped/doubled quotes, PostgreSQL dollar-quoted
    strings, and Oracle PL/SQL blocks terminated by a slash-only line.
    """
    dialect = normalize_driver(driver)
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    dollar_quote: str | None = None
    line_comment = False
    block_depth = 0
    index = 0

    def flush() -> None:
        statement = ''.join(current).strip()
        if statement:
            statements.append(statement)
        current.clear()

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ''

        if line_comment:
            if char in '\r\n':
                current.append(char)
                line_comment = False
            index += 1
            continue

        if block_depth:
            if char == '/' and next_char == '*':
                block_depth += 1
                index += 2
            elif char == '*' and next_char == '/':
                block_depth -= 1
                index += 2
            else:
                if char in '\r\n':
                    current.append(char)
                index += 1
            continue

        if dollar_quote:
            if text.startswith(dollar_quote, index):
                current.append(dollar_quote)
                index += len(dollar_quote)
                dollar_quote = None
            else:
                current.append(char)
                index += 1
            continue

        if quote:
            current.append(char)
            if char == quote:
                if next_char == quote:
                    current.append(next_char)
                    index += 2
                    continue
                quote = None
            elif char == '\\' and dialect == 'mysql' and next_char:
                current.append(next_char)
                index += 2
                continue
            index += 1
            continue

        if dialect == 'oracle' and char == '/':
            line_start = text.rfind('\n', 0, index) + 1
            line_end = text.find('\n', index)
            if line_end == -1:
                line_end = len(text)
            if text[line_start:line_end].strip() == '/' and ''.join(current).strip():
                flush()
                index = line_end
                continue

        if char == '-' and next_char == '-':
            current.append(' ')
            line_comment = True
            index += 2
            continue
        if char == '/' and next_char == '*':
            current.append(' ')
            block_depth = 1
            index += 2
            continue

        if dialect == 'postgres' and char == '$':
            match = _DOLLAR_QUOTE.match(text, index)
            if match:
                dollar_quote = match.group()
                current.append(dollar_quote)
                index = match.end()
                continue

        if char in ("'", '"', '`'):
            quote = char
            current.append(char)
            index += 1
            continue

        if char == ';':
            if dialect == 'oracle' and _is_oracle_plsql(''.join(current)):
                current.append(char)
            else:
                flush()
            index += 1
            continue

        current.append(char)
        index += 1

    if quote:
        raise ValueError(f'Unterminated {quote!r} quoted value in migration')
    if block_depth:
        raise ValueError('Unterminated block comment in migration')
    flush()
    return statements
