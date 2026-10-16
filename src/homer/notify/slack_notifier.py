"""
Slack-нотификатор через Incoming Webhook.
"""

import json

from .base import BaseNotifier, NotifyEvent


class SlackNotifier(BaseNotifier):
    name = 'slack'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.slack', {}) or {}
        self.webhook_url = cfg.get('webhook_url')
        self.channel = cfg.get('channel')
        self.username = cfg.get('username', 'Homer')
        self.icon_emoji = cfg.get('icon_emoji', ':robot_face:')
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])

    def _http_post(self, url, payload):
        try:
            import requests

            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
            return r.text
        except ImportError:
            import urllib.request

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode('utf-8')

    def _format(self, event: NotifyEvent) -> str:
        icon = '✅' if event.ok else '❌'
        blocks = [
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': (
                        f"{icon} *Job #{event.job_id}* — `{event.status}`\n"
                        f"*Команда:* `{event.command}`"
                    ),
                },
            }
        ]
        fields = [
            {'type': 'mrkdwn', 'text': f"*Exit code:*\n{event.exit_code}"},
            {'type': 'mrkdwn', 'text': f"*Попыток:*\n{event.attempts}/{event.max_attempts}"},
        ]
        if event.args:
            args_str = ', '.join(f'{k}={v}' for k, v in event.args.items())
            fields.append({'type': 'mrkdwn', 'text': f"*Аргументы:*\n`{args_str}`"})
        if event.duration_sec is not None:
            fields.append(
                {'type': 'mrkdwn', 'text': f"*Длительность:*\n{round(event.duration_sec, 2)} с"}
            )
        blocks.append({'type': 'section', 'fields': fields})
        if event.error:
            blocks.append(
                {
                    'type': 'section',
                    'text': {
                        'type': 'mrkdwn',
                        'text': f"*Ошибка:*\n```{(event.error or '')[:1500]}```",
                    },
                }
            )
        return blocks

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.webhook_url:
            return

        payload = {
            'username': self.username,
            'icon_emoji': self.icon_emoji,
            'blocks': self._format(event),
        }
        if self.channel:
            payload['channel'] = self.channel

        self._http_post(self.webhook_url, payload)
