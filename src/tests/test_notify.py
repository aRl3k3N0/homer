"""Тесты нотификаторов."""

from datetime import datetime
import json

from homer.notify import NotifyManager
from homer.notify.base import NotifyEvent
from homer.notify.file_notifier import FileNotifier


def _event(status='failed'):
    return NotifyEvent(
        job_id=1,
        command='demo',
        args={'x': 1},
        status=status,
        exit_code=1 if status != 'done' else 0,
        error='boom' if status != 'done' else None,
        result=None,
        duration_sec=1.5,
        triggered_by='test',
        attempts=1,
        max_attempts=3,
        started_at=datetime.now(),
        finished_at=datetime.now(),
    )


def test_file_notifier(tmp_path):
    class FakeConfig:
        def get(self, key, default=None):
            if key == 'notifications.file':
                return {'path': str(tmp_path / 'n.jsonl')}
            return default

    n = FileNotifier(FakeConfig(), root_dir=tmp_path)
    n.send(_event())

    lines = (tmp_path / 'n.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row['job_id'] == 1
    assert row['status'] == 'failed'


def test_manager_no_notifiers(tmp_config):
    # notifications.enabled = [] — пустой менеджер
    mgr = NotifyManager(tmp_config)
    assert mgr.notifiers == []
    # emit не должен падать
    mgr.emit(_event())
