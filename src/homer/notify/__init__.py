"""
Реестр нотификаторов + загрузка плагинов через entry points.
"""

from __future__ import annotations

from importlib.metadata import entry_points
import logging

from homer.tracing import span

from ..metrics import inc_error, inc_notify
from .base import BaseNotifier, NotifyEvent
from .desktop_notifier import DesktopNotifier
from .discord_notifier import DiscordNotifier
from .email_notifier import EmailNotifier
from .file_notifier import FileNotifier
from .log_notifier import LogNotifier
from .mattermost_notifier import MattermostNotifier
from .rocketchat_notifier import RocketChatNotifier
from .slack_notifier import SlackNotifier
from .teams_notifier import TeamsNotifier
from .telegram_notifier import TelegramNotifier

_log = logging.getLogger('homer.notify')

# Встроенные нотификаторы
REGISTRY: dict[str, type[BaseNotifier]] = {
    'email': EmailNotifier,
    'file': FileNotifier,
    'log': LogNotifier,
    'desktop': DesktopNotifier,
    'telegram': TelegramNotifier,
    'slack': SlackNotifier,
    'mattermost': MattermostNotifier,
    'rocketchat': RocketChatNotifier,
    'discord': DiscordNotifier,
    'teams': TeamsNotifier,
}


def _load_plugins():
    """
    Загружает плагины через entry point 'homer.notifiers'.

    Плагин регистрируется в pyproject.toml своего пакета так:

        [project.entry-points."homer.notifiers"]
        my_channel = "my_package.notifier:MyNotifier"

    MyNotifier должен быть подклассом BaseNotifier с заданным name.
    """
    try:
        eps = entry_points(group='homer.notifiers')
    except TypeError:
        # Python 3.9: entry_points() возвращает dict
        eps = entry_points().get('homer.notifiers', [])

    for ep in eps:
        try:
            cls = ep.load()
        except Exception as e:
            _log.warning(f"Не удалось загрузить плагин нотификатора '{ep.name}': {e}")
            continue

        if not (isinstance(cls, type) and issubclass(cls, BaseNotifier)):
            _log.warning(f"Плагин '{ep.name}' должен быть подклассом BaseNotifier")
            continue

        name = getattr(cls, 'name', None) or ep.name
        REGISTRY[name] = cls
        _log.info(f"Зарегистрирован плагин нотификатора '{name}' ({cls.__module__}.{cls.__name__})")


# Загружаем плагины при импорте пакета
_load_plugins()


class NotifyManager:
    def __init__(self, config, logger=None, root_dir=None, mailer_factory=None):
        self.config = config
        self.logger = logger
        self.root_dir = root_dir
        self.notifiers = []

        cfg = config.get('notifications', {}) or {}
        for name in cfg.get('enabled', []):
            cls = REGISTRY.get(name)
            if cls is None:
                if logger:
                    logger.warning(f"Неизвестный нотификатор: {name}", command='notify')
                continue
            try:
                if name == 'log':
                    if not logger:
                        continue
                    self.notifiers.append(cls(config, logger))
                elif name == 'email':
                    self.notifiers.append(cls(config, root_dir, mailer_factory))
                elif name == 'file':
                    self.notifiers.append(cls(config, root_dir))
                else:
                    self.notifiers.append(cls(config))
            except Exception as e:
                if logger:
                    logger.error(
                        f"[notify] init {name} failed: {e}", command='notify', exc_info=True
                    )

    def emit(self, event):
        for n in self.notifiers:
            with span(
                f'notify.{n.name}',
                kind='client',
                attributes={
                    'notify.provider': n.name,
                    'notify.status': event.status,
                    'notify.job_id': event.job_id,
                },
            ):
                try:
                    n.send(event)
                    inc_notify(n.name, 'ok')
                except Exception as e:
                    inc_notify(n.name, 'error')
                    inc_error('notify')
                    if self.logger:
                        self.logger.error(
                            f"[notify] {n.name} failed: {e}",
                            command='notify',
                            exc_info=True,
                        )

    def emit_from_job(self, job):
        from datetime import datetime

        event = NotifyEvent(
            job_id=job.id,
            command=job.command,
            args=job.args or {},
            status=job.status,
            exit_code=job.exit_code,
            error=job.error,
            result=job.result,
            duration_sec=(
                (job.finished_at - job.started_at).total_seconds()
                if job.finished_at and job.started_at
                else None
            ),
            triggered_by=job.triggered_by,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            started_at=job.started_at,
            finished_at=job.finished_at or datetime.now(),
        )
        self.emit(event)


__all__ = [
    'REGISTRY',
    'BaseNotifier',
    'DiscordNotifier',
    'EmailNotifier',
    'MattermostNotifier',
    'NotifyEvent',
    'NotifyManager',
    'RocketChatNotifier',
    'SlackNotifier',
    'TeamsNotifier',
    'TelegramNotifier',
]
