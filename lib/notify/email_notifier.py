"""
Email-нотификатор.
"""
from .base import BaseNotifier, NotifyEvent


class EmailNotifier(BaseNotifier):
    name = 'email'

    def __init__(self, config, root_dir=None, mailer_factory=None):
        super().__init__(config)
        cfg = config.get('notifications.email', {}) or {}
        self.to = cfg.get('to', [])
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])
        self.from_addr = cfg.get('from')
        self.root_dir = root_dir
        self.mailer_factory = mailer_factory
        self._mailer = None

    def _get_mailer(self):
        if self._mailer is None:
            if self.mailer_factory:
                self._mailer = self.mailer_factory()
            else:
                from lib.mailer import Mailer
                templates = (self.root_dir / 'email') if self.root_dir else None
                self._mailer = Mailer(self.config, templates)
        return self._mailer

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.to:
            return

        template = 'notifications/job_ok' if event.ok else 'notifications/job_failed'
        context = {
            'job_id': event.job_id,
            'command': event.command,
            'args': event.args,
            'args_pretty': '\n'.join(f'{k}={v}' for k, v in event.args.items()),
            'status': event.status,
            'exit_code': event.exit_code,
            'error': event.error or '',
            'result': (event.result or '')[:5000],
            'duration': round(event.duration_sec, 2) if event.duration_sec else None,
            'triggered_by': event.triggered_by or '',
            'attempts': event.attempts,
            'max_attempts': event.max_attempts,
            'started_at': event.started_at,
            'finished_at': event.finished_at,
            'ok': event.ok,
        }
        self._get_mailer().send(
            to=self.to, template_name=template,
            context=context, from_addr=self.from_addr,
        )