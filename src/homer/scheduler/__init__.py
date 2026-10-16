from .base import BaseStorage, Task
from .cron import CronExpression
from .runner import Scheduler
from .storage import DBStorage


def create_storage(config, db=None):
    """
    Создаёт хранилище задач.

    config — объект Config
    db     — опционально готовый драйвер из lib.db (если хотите использовать
             уже открытое соединение)
    """
    return DBStorage(config, db=db)


__all__ = [
    'BaseStorage',
    'CronExpression',
    'DBStorage',
    'Scheduler',
    'Task',
    'create_storage',
]
