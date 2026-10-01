# Тестирование

## Запуск

```bash
pip install -r requirements-dev.txt
pytest                          # все тесты
pytest tests/test_cron.py       # один файл
pytest -k "retry" -v            # по имени
pytest --cov=lib --cov-report=term-missing
```

## Структура

```
tests/
├── conftest.py                 # фикстуры
├── test_arguments.py
├── test_config.py
├── test_command_loader.py
├── test_cron.py
├── test_queue_storage.py
├── test_queue_dispatcher.py
├── test_mailer.py
├── test_notify.py
└── test_scheduler.py
```

## Фикстуры

```tests/conftest.py``` даёт:

* ```tmp_config``` — временный ```config.yml``` с SQLite.
* ```sqlite_storage``` — свежий ```QueueStorage``` на временной БД.
* ```sqlite_scheduler_storage``` — ```DBStorage``` для задач.
* ```sample_command_dir``` — папка с готовой командой.

## Пример

```pycon
def test_queue_push_and_get(sqlite_storage):
    from lib.queue import QueueJob, JobStatus

    job = QueueJob(command='hello', args={'name': 'world'})
    job_id = sqlite_storage.push(job)

    got = sqlite_storage.get(job_id)
    assert got is not None
    assert got.command == 'hello'
    assert got.args == {'name': 'world'}
    assert got.status == JobStatus.PENDING
```

## Что тестируем

* Парсинг аргументов, приведение типов.
* Config: ```get```, вложенные ключи, defaults.
* Command loader: команды верхнего уровня, ```foo:bar```, ```foo/main.py```.
* Cron: парсинг выражений, ```matches()```.
* QueueStorage: push, acquire_next (атомарность, attempts++), finish/retry, cancel (каскад).
* Dispatcher: push, later, sync call.
* Mailer: рендер шаблонов, file-транспорт, тема.
* Notify: file-нотификатор, log-нотификатор, кастомный.
* Scheduler: tick создаёт job, обработка очереди.

## Написание своего теста

```pycon
# tests/test_my_feature.py
import pytest

def test_something(sqlite_storage):
    ...
```

Используйте ```tmp_path``` pytest для файлов и БД.
