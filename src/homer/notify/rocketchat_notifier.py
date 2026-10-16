"""
Rocket.Chat — Incoming Webhook.

Конфиг (notifications.rocketchat):
    webhook_url: "https://chat.example.com/hooks/xxx/yyy"
    channel: "#alerts"
    username: Homer
    icon_emoji: ":robot:"
    alias: Homer
    on: [failed, timeout, canceled]
    attachment_color: "#ff0000"
"""

import json

from .base import BaseNotifier, NotifyEvent


class RocketChatNotifier(BaseNotifier):
    name = 'rocketchat'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.rocketchat', {}) or {}
        self.webhook_url = cfg.get('webhook_url')
        self.channel = cfg.get('channel')
        self.username = cfg.get('username', 'Homer')
        self.alias = cfg.get('alias', 'Homer')
        self.icon_emoji = cfg.get('icon_emoji', ':robot:')
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])
        self.color = cfg.get('attachment_color', '#e74c3c')

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

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.webhook_url:
            return

        icon = '✅' if event.ok else '❌'
        title = f"{icon} Job #{event.job_id} ({event.command}) — {event.status}"

        fields = [
            {'title': 'Exit code', 'value': str(event.exit_code), 'short': True},
            {'title': 'Попыток', 'value': f"{event.attempts}/{event.max_attempts}", 'short': True},
        ]
        if event.args:
            fields.append({'title': 'Аргументы', 'value': str(event.args), 'short': False})
        if event.duration_sec is not None:
            fields.append(
                {
                    'title': 'Длительность',
                    'value': f"{round(event.duration_sec, 2)}с",
                    'short': True,
                }
            )

        text = f"*{title}*"
        if event.error:
            text += f"\n```\n{(event.error or '')[:1500]}\n```"

        payload = {
            'alias': self.alias,
            'text': text,
            'attachments': [
                {
                    'color': self.color if not event.ok else '#2ecc71',
                    'fields': fields,
                    'footer': 'Homer',
                }
            ],
        }
        if self.channel:
            payload['channel'] = self.channel
        if self.username:
            payload['username'] = self.username
        if self.icon_emoji:
            payload['emoji'] = self.icon_emoji

        self._http_post(self.webhook_url, payload)
