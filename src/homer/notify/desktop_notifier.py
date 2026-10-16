"""
Linux: notify-send / macOS: osascript.
"""

import platform
import shutil
import subprocess

from .base import BaseNotifier, NotifyEvent


class DesktopNotifier(BaseNotifier):
    name = 'desktop'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('notifications.desktop', {}) or {}
        self.on = cfg.get('on', ['failed', 'timeout'])

    def send(self, event: NotifyEvent):
        if event.status not in self.on:
            return
        title = f"Homer: {event.status} — job #{event.job_id}"
        body = event.short_command
        if event.error:
            body += f"\n{event.error[:200]}"

        sysname = platform.system()
        try:
            if sysname == 'Linux' and shutil.which('notify-send'):
                subprocess.run(['notify-send', title, body], timeout=5)
            elif sysname == 'Darwin':
                script = f'display notification "{body}" with title "{title}"'
                subprocess.run(['osascript', '-e', script], timeout=5)
        except Exception:
            pass
