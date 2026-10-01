"""
Модели очереди задач.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json


class JobStatus:
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    CANCELED = 'canceled'
    TIMEOUT = 'timeout'


@dataclass
class QueueJob:
    id: Optional[int] = None
    command: str = ''
    args: dict = field(default_factory=dict)
    priority: int = 0
    status: str = JobStatus.PENDING
    result: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    run_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    parent_job_id: Optional[int] = None
    locked_by: Optional[str] = None
    lease_until: Optional[datetime] = None
    run_id: Optional[str] = None
    triggered_by: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    retry_delay: int = 60
    last_attempt_at: Optional[datetime] = None
    cancel_requested: bool = False
    timeout_sec: Optional[int] = None

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
            command=d.get('command') or '',
            args=args or {},
            priority=d.get('priority', 0) or 0,
            status=d.get('status') or JobStatus.PENDING,
            result=d.get('result'),
            exit_code=d.get('exit_code'),
            error=d.get('error'),
            created_at=_parse_dt(d.get('created_at')),
            run_at=_parse_dt(d.get('run_at')),
            started_at=_parse_dt(d.get('started_at')),
            finished_at=_parse_dt(d.get('finished_at')),
            parent_job_id=d.get('parent_job_id'),
            locked_by=d.get('locked_by'),
            lease_until=_parse_dt(d.get('lease_until')),
            run_id=d.get('run_id'),
            triggered_by=d.get('triggered_by'),
            attempts=d.get('attempts', 0) or 0,
            max_attempts=d.get('max_attempts', 3) or 3,
            retry_delay=d.get('retry_delay', 60) or 60,
            last_attempt_at=_parse_dt(d.get('last_attempt_at')),
            cancel_requested=bool(d.get('cancel_requested', False)),
            timeout_sec=d.get('timeout_sec'),
        )


def _parse_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(str(v), fmt)
            except ValueError:
                continue
    return None