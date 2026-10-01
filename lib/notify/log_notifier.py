"""
Пишет в основной лог Homer.
"""
from .base import BaseNotifier, NotifyEvent


class LogNotifier(BaseNotifier):
    name = 'log'

    def __init__(self, config, logger):
        super().__init__(config)
        self.logger = logger
        cfg = config.get('notifications.log', {}) or {}
        self.level = cfg.get('level', 'info')
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        level = self.level
        if not event.ok and level == 'info':
            level = 'error'
        msg = (f"[notify] job #{event.job_id} {event.short_command} → "
               f"{event.status} (exit={event.exit_code}, "
               f"attempts={event.attempts}/{event.max_attempts})")
        if event.error:
            msg += f" error={event.error[:200]}"
        getattr(self.logger, level, self.logger.info)(msg, command='notify')