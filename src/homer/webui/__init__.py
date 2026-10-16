"""
Web-UI для мониторинга очереди Homer.

Реализация: FastAPI + Jinja2 + HTMX.
Поддерживает авторизацию через Basic Auth (опционально).
"""

from .app import create_app

__all__ = ['create_app']
