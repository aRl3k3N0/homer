"""
Общие фикстуры для бенчмарков.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_config(tmp_path):
    from lib.config import Config
    cfg = tmp_path / 'config.yml'
    cfg.write_text(
        f"""
app:
  name: HomerBench
  version: 0.0.1
logging:
  level: CRITICAL
  console: false
scheduler:
  storage: sqlite
  sqlite:
    path: {tmp_path / 'scheduler.db'}
notifications:
  enabled: []
""",
        encoding='utf-8',
    )
    return Config(cfg)


@pytest.fixture
def sqlite_storage(tmp_config):
    from lib.queue import QueueStorage
    s = QueueStorage(tmp_config)
    yield s
    s.close()
