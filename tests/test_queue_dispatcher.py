"""Тесты Dispatcher (без воркеров — только push/call таймаут)."""

import pytest

from lib.queue import Dispatcher, QueueTimeout


def test_push(sqlite_storage, tmp_config):
    d = Dispatcher(sqlite_storage, config=tmp_config, triggered_by='test')
    job_id = d.push('hello', name='w', priority=10)
    job = d.get(job_id)
    assert job.command == 'hello'
    assert job.args == {'name': 'w'}
    assert job.priority == 10
    assert job.triggered_by == 'test'


def test_later(sqlite_storage, tmp_config):
    d = Dispatcher(sqlite_storage, config=tmp_config)
    job_id = d.later('x', minutes=5)
    job = d.get(job_id)
    assert job.run_at is not None
    assert job.run_at > job.created_at


def test_call_timeout(sqlite_storage, tmp_config):
    d = Dispatcher(sqlite_storage, config=tmp_config)
    with pytest.raises(QueueTimeout):
        d.call('nobody-will-run', timeout=1, poll_interval=0.1)
