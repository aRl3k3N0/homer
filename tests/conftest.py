"""
Общие фикстуры для тестов Homer.
"""

from pathlib import Path
import sys

import pytest

# Добавляем корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_config(tmp_path):
    """Временный config.yml с sqlite-хранилищем."""
    from lib.config import Config

    cfg_path = tmp_path / 'config.yml'
    cfg_path.write_text(
        f"""
app:
  name: HomerTest
  version: 0.0.1

logging:
  level: CRITICAL
  console: false

scheduler:
  storage: sqlite
  sqlite:
    path: {tmp_path / 'scheduler.db'}
  lease_seconds: 60
  heartbeat_interval: 5
  max_workers: 2

notifications:
  enabled: []
""",
        encoding='utf-8',
    )
    return Config(cfg_path)


@pytest.fixture
def sqlite_storage(tmp_config):
    """Свежий QueueStorage на временной SQLite."""
    from lib.queue import QueueStorage

    storage = QueueStorage(tmp_config)
    yield storage
    storage.close()


@pytest.fixture
def sqlite_scheduler_storage(tmp_config):
    """Свежий DBStorage для cron-задач."""
    from lib.scheduler import create_storage

    storage = create_storage(tmp_config)
    yield storage
    storage.close()


@pytest.fixture
def sample_command_dir(tmp_path):
    """Папка с готовой командой hello для CommandLoader."""
    commands = tmp_path / 'commands'
    commands.mkdir()
    (commands / '__init__.py').write_text('', encoding='utf-8')
    (commands / 'hello.py').write_text(
        'DESCRIPTION = "Привет"\ndef execute(context):\n    return 0\n',
        encoding='utf-8',
    )
    sub = commands / 'report'
    sub.mkdir()
    (sub / '__init__.py').write_text('', encoding='utf-8')
    (sub / 'daily.py').write_text(
        'DESCRIPTION = "Ежедневно"\ndef execute(context):\n    return 0\n',
        encoding='utf-8',
    )
    return commands
