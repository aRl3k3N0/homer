"""
Discord — Webhook с embeds.

Конфиг (notifications.discord):
    webhook_url: "https://discord.com/api/webhooks/xxx/yyy"
    username: Homer
    avatar_url: "https://..."
    on: [failed, timeout, canceled]
    mention_on_fail: "@here"   # опционально
"""
import json

from .base import BaseNotifier, NotifyEvent


class DiscordNotifier(BaseNotifier):
    name = 'discord'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.discord', {}) or {}
        self.webhook_url = cfg.get('webhook_url')
        self.username = cfg.get('username', 'Homer')
        self.avatar_url = cfg.get('avatar_url')
        self.mention_on_fail = cfg.get('mention_on_fail')
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
                url, data=data,
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode('utf-8')

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.webhook_url:
            return

        color = 0x2ecc71 if event.ok else (0xf39c12 if event.status in
                                          ('timeout', 'canceled') else 0xe74c3c)

        icon = '✅' if event.ok else '❌'
        embed = {
            'title': f"{icon} Job #{event.job_id} ({event.command}) — {event.status}",
            'color': color,
            'fields': [],
            'footer': {'text': 'Homer'},
        }

        embed['fields'].append({'name': 'Exit code', 'value': str(event.exit_code), 'inline': True})
        embed['fields'].append({'name': 'Попыток',
                                 'value': f"{event.attempts}/{event.max_attempts}",
                                 'inline': True})
        if event.args:
            embed['fields'].append({'name': 'Аргументы', 'value': f"`{event.args}`"[:1024]})
        if event.duration_sec is not None:
            embed['fields'].append({'name': 'Длительность',
                                     'value': f"{round(event.duration_sec, 2)}с",
                                     'inline': True})
        if event.error:
            embed['description'] = f"```{(event.error or '')[:1500]}```"

        content = ''
        if not event.ok and self.mention_on_fail:
            content = self.mention_on_fail

        payload = {
            'content': content,
            'embeds': [embed],
        }
        if self.username:
            payload['username'] = self.username
        if self.avatar_url:
            payload['avatar_url'] = self.avatar_url

        self._http_post(self.webhook_url, payload)
