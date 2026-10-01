"""Тесты QueueStorage."""
from datetime import datetime, timedelta

from lib.queue import QueueJob, JobStatus


def test_push_and_get(sqlite_storage):
    job_id = sqlite_storage.push(QueueJob(command='hello', args={'name': 'w'}))
    got = sqlite_storage.get(job_id)
    assert got is not None
    assert got.command == 'hello'
    assert got.args == {'name': 'w'}
    assert got.status == JobStatus.PENDING
    assert got.attempts == 0
    assert got.max_attempts == 3


def test_acquire_increments_attempts(sqlite_storage):
    sqlite_storage.push(QueueJob(command='hello'))

    job = sqlite_storage.acquire_next(lease_seconds=60)
    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.attempts == 1

    # Повторный acquire без finish — не должен вернуть тот же job
    second = sqlite_storage.acquire_next(lease_seconds=60)
    assert second is None


def test_finish_and_retry(sqlite_storage):
    sqlite_storage.push(QueueJob(command='x', max_attempts=3, retry_delay=0))
    job = sqlite_storage.acquire_next(60)
    assert job.attempts == 1

    sqlite_storage.finish(job.id, job.run_id, JobStatus.FAILED, error='boom')
    again = sqlite_storage.get(job.id)
    assert again.status == JobStatus.PENDING
    assert again.attempts == 1  # счётчик уже инкрементирован в acquire

    # Ещё раз
    job2 = sqlite_storage.acquire_next(60)
    assert job2.attempts == 2
    sqlite_storage.finish(job2.id, job2.run_id, JobStatus.FAILED, error='boom')
    again2 = sqlite_storage.get(job.id)
    assert again2.status == JobStatus.PENDING

    # Третья попытка — окончательный failed
    job3 = sqlite_storage.acquire_next(60)
    assert job3.attempts == 3
    sqlite_storage.finish(job3.id, job3.run_id, JobStatus.FAILED, error='boom')
    final = sqlite_storage.get(job.id)
    assert final.status == JobStatus.FAILED


def test_cascade_cancel(sqlite_storage):
    parent_id = sqlite_storage.push(QueueJob(command='parent'))
    child_id = sqlite_storage.push(QueueJob(command='child', parent_job_id=parent_id))
    grandchild = sqlite_storage.push(QueueJob(command='g', parent_job_id=child_id))

    n = sqlite_storage.cancel(parent_id, cascade=True)
    assert n >= 3

    assert sqlite_storage.get(parent_id).status == JobStatus.CANCELED
    assert sqlite_storage.get(child_id).status == JobStatus.CANCELED
    assert sqlite_storage.get(grandchild).status == JobStatus.CANCELED


def test_cancel_no_cascade(sqlite_storage):
    parent_id = sqlite_storage.push(QueueJob(command='parent'))
    child_id = sqlite_storage.push(QueueJob(command='child', parent_job_id=parent_id))

    sqlite_storage.cancel(parent_id, cascade=False)
    assert sqlite_storage.get(parent_id).status == JobStatus.CANCELED
    assert sqlite_storage.get(child_id).status == JobStatus.PENDING


def test_retry(sqlite_storage):
    job_id = sqlite_storage.push(QueueJob(command='x'))
    job = sqlite_storage.acquire_next(60)
    sqlite_storage.finish(job.id, job.run_id, JobStatus.FAILED, error='x')
    # после этого attempts=1, статус pending
    sqlite_storage.retry(job_id)
    j = sqlite_storage.get(job_id)
    assert j.status == JobStatus.PENDING
    assert j.attempts == 0
    assert j.error is None


def test_stats(sqlite_storage):
    sqlite_storage.push(QueueJob(command='a'))
    sqlite_storage.push(QueueJob(command='b'))
    s = sqlite_storage.stats()
    assert s[JobStatus.PENDING] == 2


def test_delayed_run_at(sqlite_storage):
    future = datetime.now() + timedelta(hours=1)
    sqlite_storage.push(QueueJob(command='x', run_at=future))
    assert sqlite_storage.acquire_next(60) is None