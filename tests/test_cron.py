"""Тесты CronExpression."""

from datetime import datetime

import pytest

from lib.scheduler.cron import CronExpression


def test_star():
    c = CronExpression('* * * * *')
    assert c.matches(datetime(2026, 9, 19, 10, 30))


def test_minute():
    c = CronExpression('15 * * * *')
    assert c.matches(datetime(2026, 9, 19, 10, 15))
    assert not c.matches(datetime(2026, 9, 19, 10, 16))


def test_step():
    c = CronExpression('*/5 * * * *')
    assert c.matches(datetime(2026, 9, 19, 10, 0))
    assert c.matches(datetime(2026, 9, 19, 10, 5))
    assert not c.matches(datetime(2026, 9, 19, 10, 7))


def test_range():
    c = CronExpression('0 9-18 * * *')
    assert c.matches(datetime(2026, 9, 19, 9, 0))
    assert c.matches(datetime(2026, 9, 19, 18, 0))
    assert not c.matches(datetime(2026, 9, 19, 8, 0))


def test_weekday():
    # 2026-09-19 — суббота (weekday=5 в Python, но 6 в cron)
    c = CronExpression('0 0 * * 6')
    assert c.matches(datetime(2026, 9, 19, 0, 0))


def test_invalid():
    with pytest.raises(ValueError):
        CronExpression('* * *')
    with pytest.raises(ValueError):
        CronExpression('99 * * * *')
