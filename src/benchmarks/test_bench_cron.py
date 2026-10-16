"""
Бенчмарки CronExpression.
"""
from datetime import datetime

from homer.scheduler.cron import CronExpression


def test_bench_parse_star(benchmark):
    benchmark(CronExpression, '* * * * *')


def test_bench_parse_complex(benchmark):
    benchmark(CronExpression, '*/5 9-18 1,15 * 1-5')


def test_bench_matches(benchmark):
    c = CronExpression('*/5 * * * *')
    dt = datetime(2026, 9, 19, 10, 30)
    benchmark(c.matches, dt)


def test_bench_matches_many(benchmark):
    c = CronExpression('0 0 * * *')
    now = datetime(2026, 9, 19, 0, 0)

    def run():
        for _ in range(1000):
            c.matches(now)
    benchmark(run)
