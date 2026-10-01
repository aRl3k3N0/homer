from .base import BaseStorage, Task
from .storage import DBStorage
from .cron import CronExpression
from .runner import Scheduler


def create_storage(config, db=None):
    """
    Создаёт хранилище задач.

    config — объект Config
    db     — опционально готовый драйвер из lib.db (если хотите использовать
             уже открытое соединение)
    """
    return DBStorage(config, db=db)


__all__ = ['BaseStorage', 'Task', 'Scheduler', 'DBStorage',
           'CronExpression', 'create_storage']