"""
Парсер cron-выражений (5 полей).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional


class CronExpression:
    def __init__(self, expr: str) -> None:
        self.expr = expr.strip()
        parts = self.expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"Ожидается 5 полей в cron-выражении, получено {len(parts)}: '{expr}'"
            )
        self.minute = self._parse(parts[0], 0, 59)
        self.hour = self._parse(parts[1], 0, 23)
        self.day = self._parse(parts[2], 1, 31)
        self.month = self._parse(parts[3], 1, 12)
        self.weekday = self._parse(parts[4], 0, 6, sunday_7=True)

    @staticmethod
    def _parse(field, lo, hi, sunday_7=False):
        values = set()
        if field == '*':
            return set(range(lo, hi + 1))
        for part in field.split(','):
            part = part.strip()
            if part.startswith('*/'):
                step = int(part[2:])
                if step <= 0:
                    raise ValueError(f"Шаг должен быть > 0: {part}")
                values.update(range(lo, hi + 1, step))
                continue
            if '-' in part:
                a, b = part.split('-', 1)
                a, b = int(a), int(b)
                if sunday_7:
                    a = 0 if a == 7 else a
                    b = 0 if b == 7 else b
                if a > b:
                    values.update(range(a, hi + 1))
                    values.update(range(lo, b + 1))
                else:
                    values.update(range(a, b + 1))
                continue
            v = int(part)
            if sunday_7 and v == 7:
                v = 0
            if not (lo <= v <= hi):
                raise ValueError(f"Значение {v} вне диапазона [{lo}, {hi}]")
            values.add(v)
        return values

    def matches(self, dt: Optional[datetime] = None) -> bool:
        dt = dt or datetime.now()
        py_wd = dt.weekday()
        cron_wd = (py_wd + 1) % 7
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.day
            and dt.month in self.month
            and cron_wd in self.weekday
        )

    def __str__(self):
        return self.expr