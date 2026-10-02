"""
Пишет события в JSONL-файл.
"""

import json
from pathlib import Path

from .base import BaseNotifier, NotifyEvent


class FileNotifier(BaseNotifier):
    name = 'file'

    def __init__(self, config, root_dir=None):
        super().__init__(config)
        cfg = config.get('notifications.file', {}) or {}
        path = cfg.get('path', 'var/notifications.jsonl')
        self.path = Path(path)
        if not self.path.is_absolute() and root_dir:
            self.path = Path(root_dir) / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, event: NotifyEvent):
        row = {
            'job_id': event.job_id,
            'command': event.command,
            'args': event.args,
            'status': event.status,
            'exit_code': event.exit_code,
            'error': event.error,
            'duration_sec': event.duration_sec,
            'triggered_by': event.triggered_by,
            'attempts': event.attempts,
            'max_attempts': event.max_attempts,
            'started_at': event.started_at.isoformat() if event.started_at else None,
            'finished_at': event.finished_at.isoformat(),
        }
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
