"""
Telegram-нотификатор через Bot API.
Использует requests (если установлен). Иначе — urllib.
"""
import json

from .base import BaseNotifier, NotifyEvent


class TelegramNotifier(BaseNotifier):
    name = 'telegram'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.telegram', {}) or {}
        self.bot_token = cfg.get('bot_token')
        self.chat_ids = cfg.get('chat_ids') or (
            [cfg['chat_id']] if cfg.get('chat_id') else []
        )
        self.on = cfg.get('on', ['failed', 'timeout', 'canceled'])
        self.parse_mode = cfg.get('parse_mode', 'HTML')
        self._base_url = f"https://api.telegram.org/bot{self.bot_token}"

    def _http_post(self, url, payload):
        try:
            import requests
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
            return r.json()
        except ImportError:
            import urllib.request
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, data=data,
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8'))

    def _format(self, event: NotifyEvent) -> str:
        icon = '✅' if event.ok else '❌'
        lines = [
            f"{icon} <b>Job #{event.job_id}</b> — <code>{event.status}</code>",
            f"<b>Команда:</b> <code>{event.command}</code>",
        ]
        if event.args:
            args_str = ', '.join(f'{k}={v}' for k, v in event.args.items())
            lines.append(f"<b>Аргументы:</b> <code>{args_str}</code>")
        lines.append(f"<b>Exit code:</b> {event.exit_code}")
        lines.append(f"<b>Попыток:</b> {event.attempts}/{event.max_attempts}")
        if event.duration_sec is not None:
            lines.append(f"<b>Длительность:</b> {round(event.duration_sec, 2)} с")
        if event.triggered_by:
            lines.append(f"<b>Источник:</b> <code>{event.triggered_by}</code>")
        if event.error:
            lines.append(f"<b>Ошибка:</b>\n<pre>{(event.error or '')[:1000]}</pre>")
        return '\n'.join(lines)

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        if not self.bot_token or not self.chat_ids:
            return

        text = self._format(event)
        for chat_id in self.chat_ids:
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': self.parse_mode,
                'disable_web_page_preview': True,
            }
            try:
                self._http_post(f"{self._base_url}/sendMessage", payload)
            except Exception:
                # Молча игнорируем — ошибку запишет NotifyManager
                raise