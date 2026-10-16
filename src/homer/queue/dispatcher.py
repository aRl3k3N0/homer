"""
Диспетчер очереди. Команды используют его, чтобы вызывать другие команды.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Any, Optional

from .models import JobStatus, QueueJob


class QueueTimeout(Exception):
    """Не дождались результата задачи за отведённое время"""


@dataclass
class QueueResult:
    job_id: int
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None

    @property
    def ok(self):
        return self.status == JobStatus.DONE and (self.exit_code in (None, 0))


class Dispatcher:
    def __init__(
        self, storage, config=None, triggered_by=None, default_timeout=300, poll_interval=1.0
    ):
        self.storage = storage
        self.config = config
        self.triggered_by = triggered_by
        self.default_timeout = default_timeout
        self.poll_interval = poll_interval
        self._parent_job_id = None

    def push(
        self,
        command: str,
        *,
        priority: int = 0,
        run_at: Optional[datetime] = None,
        parent_job_id: Optional[int] = None,
        triggered_by: Optional[str] = None,
        max_attempts: Optional[int] = None,
        retry_delay: Optional[int] = None,
        timeout_sec: Optional[int] = None,
        **args: Any,
    ) -> int:
        qd = (self.config.get('scheduler.queue_defaults', {}) or {}) if self.config else {}
        job = QueueJob(
            command=command,
            args=args,
            priority=priority,
            status=JobStatus.PENDING,
            run_at=run_at,
            parent_job_id=parent_job_id or self._parent_job_id,
            triggered_by=triggered_by or self.triggered_by,
            max_attempts=(
                max_attempts if max_attempts is not None else int(qd.get('max_attempts', 3))
            ),
            retry_delay=(
                retry_delay if retry_delay is not None else int(qd.get('retry_delay', 60))
            ),
            timeout_sec=timeout_sec,
        )
        return self.storage.push(job)

    def later(
        self, command: str, *, seconds: int = 0, minutes: int = 0, hours: int = 0, **kwargs: Any
    ) -> int:
        run_at = datetime.now() + timedelta(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
        )
        return self.push(command, run_at=run_at, **kwargs)

    def call(
        self,
        command: str,
        *,
        timeout: Optional[int] = None,
        poll_interval: Optional[float] = None,
        priority: int = 100,
        parent_job_id: Optional[int] = None,
        max_attempts: int = 1,
        **args: Any,
    ) -> QueueResult:
        """
        Кладёт задачу в очередь и ждёт её завершения.
        """
        timeout = timeout if timeout is not None else self.default_timeout
        poll_interval = poll_interval or self.poll_interval

        job_id = self.push(
            command,
            priority=priority,
            parent_job_id=parent_job_id,
            max_attempts=max_attempts,
            **args,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.storage.get(job_id)
            if job is None:
                raise RuntimeError(f"Задача {job_id} исчезла из очереди")

            if job.status == JobStatus.DONE:
                return QueueResult(
                    job_id=job_id,
                    status=job.status,
                    output=job.result,
                    exit_code=job.exit_code or 0,
                )
            if job.status == JobStatus.FAILED:
                return QueueResult(
                    job_id=job_id,
                    status=job.status,
                    output=job.result,
                    error=job.error,
                    exit_code=job.exit_code,
                )
            if job.status == JobStatus.TIMEOUT:
                raise QueueTimeout(f"Задача '{command}' (id={job_id}) превысила таймаут")
            if job.status == JobStatus.CANCELED:
                raise QueueTimeout(f"Задача '{command}' (id={job_id}) отменена")

            time.sleep(poll_interval)

        self.storage.cancel(job_id, cascade=True, reason=f"call timeout after {timeout}s")
        raise QueueTimeout(f"Не дождались '{command}' (id={job_id}) за {timeout}с")

    def get(self, job_id):
        return self.storage.get(job_id)

    def list(self, status=None, limit=100):
        return self.storage.list(status=status, limit=limit)

    def stats(self):
        return self.storage.stats()

    def cancel(self, job_id):
        return self.storage.cancel(job_id, cascade=True)
