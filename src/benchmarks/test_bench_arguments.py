"""
Бенчмарки ArgumentParser.
"""
from homer.core.arguments import ArgumentParser


def test_bench_parse_simple(benchmark):
    def run():
        p = ArgumentParser()
        p.parse(['cmd', '--user=admin', '--ver=16', '--active=true'])
        return p
    benchmark(run)


def test_bench_parse_many(benchmark):
    argv = ['cmd'] + [f'--k{i}=v{i}' for i in range(50)]

    def run():
        p = ArgumentParser()
        p.parse(argv)
        return p
    benchmark(run)


def test_bench_parse_positional(benchmark):
    argv = ['cmd'] + ['pos'] * 100

    def run():
        p = ArgumentParser()
        p.parse(argv)
        return p
    benchmark(run)
