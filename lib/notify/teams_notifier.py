"""
Microsoft Teams — Incoming Webhook с MessageCard.

Конфиг (notifications.teams):
    webhook_url: "https://outlook.office.com/webhook/..."
    on: [failed, timeout, canceled]
    color_ok: "2ecc71"
    color_fail: "e74c3c"
    theme_color: "0078D4"
"""

import json

from .base import BaseNotifier, NotifyEvent


class TeamsNotifier(BaseNotifier):
    name = 'teams'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.teams', {}) or {}
        self.webhook_url = cfg.get('webhook_url')
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])
        self.color_ok = cfg.get('color_ok', '2ecc71')
        self.color_fail = cfg.get('color_fail', 'e74c3c')

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

        theme = self.color_ok if event.ok else self.color_fail
        icon = '✅' if event.ok else '❌'

        facts = [
            {'name': 'Job ID', 'value': str(event.job_id)},
            {'name': 'Команда', 'value': event.command},
            {'name': 'Статус', 'value': event.status},
            {'name': 'Exit code', 'value': str(event.exit_code)},
            {'name': 'Попыток', 'value': f"{event.attempts}/{event.max_attempts}"},
        ]
        if event.args:
            facts.append({'name': 'Аргументы', 'value': str(event.args)})
        if event.duration_sec is not None:
            facts.append({'name': 'Длительность', 'value': f"{round(event.duration_sec, 2)}с"})
        if event.triggered_by:
            facts.append({'name': 'Источник', 'value': event.triggered_by})

        sections = [
            {
                'activityTitle': f"{icon} Job #{event.job_id}",
                'activitySubtitle': event.command,
                'facts': facts,
                'markdown': True,
            }
        ]

        if event.error:
            sections.append(
                {
                    'title': 'Ошибка',
                    'text': f"```\n{(event.error or '')[:1500]}\n```",
                }
            )

        payload = {
            '@type': 'MessageCard',
            '@context': 'https://schema.org/extensions',
            'summary': f"Homer job #{event.job_id} — {event.status}",
            'themeColor': theme,
            'title': f"Homer: job #{event.job_id} ({event.status})",
            'sections': sections,
        }

        self._http_post(self.webhook_url, payload)
