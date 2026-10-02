"""
Mattermost-нотификатор через Incoming Webhook.

Конфиг (notifications.mattermost):
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    channel:     "town-square"           # опционально
    username:    "Homer"                 # опционально
    icon_emoji:  ":robot_face:"          # опционально
    icon_url:    "https://.../icon.png"  # опционально (приоритетнее emoji)
    on:          [failed, timeout, canceled]
    color_ok:     "#2ecc71"              # цвет плашки для успешных
    color_fail:   "#e74c3c"              # цвет плашки для ошибок
    color_warn:   "#f39c12"              # цвет плашки для canceled/timeout
    mention_on_fail: "@channel"          # опционально, упоминание при ошибке
"""

import json

from .base import BaseNotifier, NotifyEvent


class MattermostNotifier(BaseNotifier):
    name = 'mattermost'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.mattermost', {}) or {}

        self.webhook_url = cfg.get('webhook_url')
        self.channel = cfg.get('channel')
        self.username = cfg.get('username', 'Homer')
        self.icon_emoji = cfg.get('icon_emoji')
        self.icon_url = cfg.get('icon_url')
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])

        self.color_ok = cfg.get('color_ok', '#2ecc71')
        self.color_fail = cfg.get('color_fail', '#e74c3c')
        self.color_warn = cfg.get('color_warn', '#f39c12')
        self.mention_on_fail = cfg.get('mention_on_fail')

    # ─────────────────── HTTP ───────────────────

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

    # ─────────────────── Формат ───────────────────

    def _color(self, event: NotifyEvent) -> str:
        if event.ok:
            return self.color_ok
        if event.status in ('canceled', 'timeout'):
            return self.color_warn
        return self.color_fail

    def _icon(self, event: NotifyEvent) -> str:
        return '✅' if event.ok else '❌'

    def _title(self, event: NotifyEvent) -> str:
        return f"{self._icon(event)} Job #{event.job_id} ({event.command}) — {event.status}"

    def _build_fields(self, event: NotifyEvent) -> list:
        fields = [
            {
                'short': True,
                'title': 'Exit code',
                'value': str(event.exit_code),
            },
            {
                'short': True,
                'title': 'Попыток',
                'value': f"{event.attempts}/{event.max_attempts}",
            },
        ]

        if event.args:
            args_str = ', '.join(f'{k}={v}' for k, v in event.args.items())
            fields.append(
                {
                    'short': False,
                    'title': 'Аргументы',
                    'value': f'`{args_str}`',
                }
            )

        if event.duration_sec is not None:
            fields.append(
                {
                    'short': True,
                    'title': 'Длительность',
                    'value': f"{round(event.duration_sec, 2)} с",
                }
            )

        if event.triggered_by:
            fields.append(
                {
                    'short': True,
                    'title': 'Источник',
                    'value': f'`{event.triggered_by}`',
                }
            )

        return fields

    def _build_text(self, event: NotifyEvent) -> str:
        parts = []

        # Верхняя строка с упоминанием при ошибке (если настроено)
        if not event.ok and self.mention_on_fail:
            parts.append(self.mention_on_fail)

        # Основной заголовок
        parts.append(f"**{self._title(event)}**")

        if event.error:
            # Обрезаем длинные трейсбеки
            err = (event.error or '')[:1500]
            parts.append(f"**Ошибка:**\n```\n{err}\n```")

        if event.ok and event.result:
            out = (event.result or '')[:1500]
            parts.append(f"**Вывод:**\n```\n{out}\n```")

        return '\n\n'.join(parts)

    # ─────────────────── Отправка ───────────────────

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.webhook_url:
            return

        payload = {
            'text': self._build_text(event),
            'username': self.username,
            'attachments': [
                {
                    'color': self._color(event),
                    'title': self._title(event),
                    'fields': self._build_fields(event),
                    'footer': 'Homer',
                }
            ],
        }

        if self.channel:
            payload['channel'] = self.channel

        # Mattermost принимает только один из icon_url / icon_emoji
        if self.icon_url:
            payload['icon_url'] = self.icon_url
        elif self.icon_emoji:
            payload['icon_emoji'] = self.icon_emoji

        self._http_post(self.webhook_url, payload)
