"""
Бенчмарки QueueStorage (SQLite in-memory).
"""
from lib.queue import QueueJob, JobStatus


def test_bench_push(benchmark, sqlite_storage):
    counter = iter(range(1, 1_000_000))

    def run():
        sqlite_storage.push(QueueJob(command='hello', args={'n': next(counter)}))
    benchmark(run)


def test_bench_acquire_and_finish(benchmark, sqlite_storage):
    def run():
        sqlite_storage.push(QueueJob(command='hello'))
        job = sqlite_storage.acquire_next(lease_seconds=60)
        sqlite_storage.finish(job.id, job.run_id, JobStatus.DONE,
                              result='ok', exit_code=0)
    benchmark(run)


def test_bench_acquire_empty(benchmark, sqlite_storage):
    benchmark(sqlite_storage.acquire_next, 60)


def test_bench_stats(benchmark, sqlite_storage):
    for i in range(100):
        sqlite_storage.push(QueueJob(command='x', priority=i % 10))
    benchmark(sqlite_storage.stats)
