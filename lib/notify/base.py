"""
Интерфейс нотификатора.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

@dataclass
class NotifyEvent:
    job_id: int
    command: str
    args: dict[str, Any]
    status: str
    exit_code: Optional[int]
    error: Optional[str]
    result: Optional[str]
    duration_sec: Optional[float]
    triggered_by: Optional[str]
    attempts: int
    max_attempts: int
    started_at: Optional[datetime]
    finished_at: datetime

    @property
    def ok(self) -> bool:
        return self.status == 'done' and (self.exit_code in (None, 0))

    @property
    def short_command(self) -> str:
        if not self.args:
            return self.command
        return (f"{self.command} ("
                + ", ".join(f"{k}={v}" for k, v in self.args.items()) + ")")


class BaseNotifier:
    name = 'base'

    def __init__(self, config):
        self.config = config

    def send(self, event: NotifyEvent):
        raise NotImplementedError