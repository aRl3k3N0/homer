"""Тесты Scheduler (создание job-ов из cron без реального запуска)."""
from datetime import datetime

from lib.scheduler import create_storage, CronExpression
from lib.scheduler.base import Task


def test_add_and_list(sqlite_scheduler_storage):
    storage = sqlite_scheduler_storage
    tid = storage.add(Task(
        name='t1', command='hello', cron='* * * * *',
        args={'name': 'world'},
    ))
    assert tid is not None
    tasks = storage.list()
    assert len(tasks) == 1
    assert tasks[0].name == 't1'
    assert tasks[0].args == {'name': 'world'}


def test_get_by_name(sqlite_scheduler_storage):
    storage = sqlite_scheduler_storage
    storage.add(Task(name='t1', command='hello', cron='* * * * *'))
    task = storage.get_by_name('t1')
    assert task is not None
    assert task.command == 'hello'


def test_acquire_task(sqlite_scheduler_storage):
    storage = sqlite_scheduler_storage
    storage.add(Task(name='t1', command='hello', cron='* * * * *'))

    task = storage.get_by_name('t1')
    assert storage.acquire_task(task.id, lease_seconds=60)
    # второй раз сразу не должно получиться
    assert not storage.acquire_task(task.id, lease_seconds=60)


def test_toggle(sqlite_scheduler_storage):
    storage = sqlite_scheduler_storage
    storage.add(Task(name='t1', command='hello', cron='* * * * *', enabled=True))
    task = storage.get_by_name('t1')
    task.enabled = False
    storage.update(task)
    again = storage.get_by_name('t1')
    assert again.enabled is False


def test_remove(sqlite_scheduler_storage):
    storage = sqlite_scheduler_storage
    storage.add(Task(name='t1', command='hello', cron='* * * * *'))
    task = storage.get_by_name('t1')
    storage.remove(task.id)
    assert storage.get_by_name('t1') is None