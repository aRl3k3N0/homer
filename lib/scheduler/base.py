"""
Базовые сущности планировщика.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import json


@dataclass
class Task:
    id: Optional[int] = None
    name: str = ''
    command: str = ''
    args: dict = field(default_factory=dict)
    cron: str = '* * * * *'
    enabled: bool = True
    description: str = ''
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    next_run: Optional[datetime] = None
    locked_by: Optional[str] = None
    lease_until: Optional[datetime] = None
    run_id: Optional[str] = None
    heartbeat_at: Optional[datetime] = None

    def args_json(self):
        return json.dumps(self.args, ensure_ascii=False)

    @classmethod
    def from_row(cls, row):
        d = dict(row) if not isinstance(row, dict) else row
        args = d.get('args')
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except Exception:
                args = {}
        return cls(
            id=d.get('id'),
            name=d.get('name') or '',
            command=d.get('command') or '',
            args=args or {},
            cron=d.get('cron') or '* * * * *',
            enabled=bool(d.get('enabled', True)),
            description=d.get('description') or '',
            last_run=d.get('last_run'),
            last_status=d.get('last_status'),
            last_error=d.get('last_error'),
            next_run=d.get('next_run'),
            locked_by=d.get('locked_by'),
            lease_until=d.get('lease_until'),
            run_id=d.get('run_id'),
            heartbeat_at=d.get('heartbeat_at'),
        )


class BaseStorage:
    def init_schema(self): raise NotImplementedError
    def add(self, task): raise NotImplementedError
    def get(self, task_id): raise NotImplementedError
    def get_by_name(self, name): raise NotImplementedError
    def list(self): raise NotImplementedError
    def update(self, task): raise NotImplementedError
    def remove(self, task_id): raise NotImplementedError
    def close(self): pass