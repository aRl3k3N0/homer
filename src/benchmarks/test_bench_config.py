"""
Бенчмарки Config.
"""


def test_bench_get_flat(benchmark, tmp_config):
    benchmark(tmp_config.get, 'app.name')


def test_bench_get_nested(benchmark, tmp_config):
    benchmark(tmp_config.get, 'scheduler.sqlite.path')


def test_bench_get_default(benchmark, tmp_config):
    benchmark(tmp_config.get, 'missing.key', 'default')
