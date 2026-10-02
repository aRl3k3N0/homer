"""
Pydantic-схемы для OpenAPI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobSchema(BaseModel):
    id: int = Field(..., description='ID задачи')
    command: str = Field(..., description='Имя команды Homer')
    args: dict[str, Any] = Field(default_factory=dict, description='Аргументы команды')
    priority: int = Field(0, description='Приоритет (больше = важнее)')
    status: str = Field(..., description='Статус: pending|running|done|failed|canceled|timeout')
    attempts: int = Field(0, description='Сделано попыток')
    max_attempts: int = Field(3, description='Максимум попыток')
    retry_delay: int = Field(60, description='Пауза между попытками, сек')
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    run_at: Optional[datetime] = Field(None, description='Не запускать раньше')
    exit_code: Optional[int] = None
    error: Optional[str] = None
    result: Optional[str] = Field(None, description='stdout команды (обрезан)')
    triggered_by: Optional[str] = Field(None, description='Кто инициировал')
    parent_job_id: Optional[int] = Field(None, description='Родительский job')


class StatsSchema(BaseModel):
    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    canceled: int = 0
    timeout: int = 0


class HealthSchema(BaseModel):
    ok: bool
    error: Optional[str] = None


class PurgeResponse(BaseModel):
    purged: int


class ErrorResponse(BaseModel):
    detail: str
