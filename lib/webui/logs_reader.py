"""
Чтение логов Homer для Web UI.

Логи лежат в logs/<command>_<YYYY-MM-DD>.log.
Формат — text или json (см. logging.format).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional


LOG_NAME_RE = re.compile(r'^(?P<command>[a-zA-Z0-9_\-]+)_(?P<date>\d{4}-\d{2}-\d{2})\.log$')

# Парсер текстового формата:
#   2026-09-21 10:30:45 | INFO     | сообщение
TEXT_LINE_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| '
    r'(?P<level>\w+)\s+\| (?P<msg>.*)$'
)


@dataclass
class LogEntry:
    ts: Optional[datetime]
    level: str
    command: str
    message: str
    raw: str
    extra: Optional[dict] = None


@dataclass
class LogFileInfo:
    command: str
    date: date
    path: Path
    size: int
    lines: Optional[int] = None


class LogsReader:
    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)

    # ─────────── Список файлов ───────────

    def list_files(self) -> list[LogFileInfo]:
        if not self.logs_dir.exists():
            return []
        result = []
        for p in sorted(self.logs_dir.glob('*.log'), reverse=True):
            m = LOG_NAME_RE.match(p.name)
            if not m:
                continue
            try:
                d = datetime.strptime(m.group('date'), '%Y-%m-%d').date()
            except ValueError:
                continue
            result.append(LogFileInfo(
                command=m.group('command'),
                date=d,
                path=p,
                size=p.stat().st_size,
            ))
        return result

    def list_commands(self) -> list[str]:
        cmds = set()
        for info in self.list_files():
            cmds.add(info.command)
        return sorted(cmds)

    # ─────────── Чтение ───────────

    def read(self, command: str, date_: date | str,
             level: Optional[str] = None,
             grep: Optional[str] = None,
             limit: int = 2000,
             tail: bool = True) -> list[LogEntry]:
        if isinstance(date_, str):
            date_ = datetime.strptime(date_, '%Y-%m-%d').date()

        path = self.logs_dir / f"{command}_{date_.isoformat()}.log"
        if not path.exists():
            return []

        entries: list[LogEntry] = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                entry = self._parse_line(line, command)
                if entry is None:
                    continue
                if level and entry.level.upper() != level.upper():
                    continue
                if grep and grep.lower() not in entry.message.lower():
                    continue
                entries.append(entry)

        if tail and len(entries) > limit:
            entries = entries[-limit:]

        return entries

    def _parse_line(self, line: str, command: str) -> Optional[LogEntry]:
        # JSON?
        if line.startswith('{'):
            try:
                data = json.loads(line)
                ts = None
                if 'ts' in data:
                    try:
                        ts = datetime.fromisoformat(data['ts'])
                    except ValueError:
                        pass
                return LogEntry(
                    ts=ts,
                    level=data.get('level', 'INFO'),
                    command=data.get('command', command),
                    message=data.get('msg', ''),
                    raw=line,
                    extra={k: v for k, v in data.items()
                           if k not in ('ts', 'level', 'command', 'msg')},
                )
            except json.JSONDecodeError:
                pass

        # Текстовый
        m = TEXT_LINE_RE.match(line)
        if m:
            try:
                ts = datetime.strptime(m.group('ts'), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                ts = None
            return LogEntry(
                ts=ts,
                level=m.group('level'),
                command=command,
                message=m.group('msg'),
                raw=line,
            )

        # Не распарсилось — отдаём как есть
        return LogEntry(ts=None, level='RAW', command=command,
                        message=line, raw=line)

    # ─────────── Follow (хвост в реальном времени) ───────────

    def tail_lines(self, command: str, date_: date | str,
                   from_offset: int = 0) -> tuple[int, list[str]]:
        """
        Читает новые строки, начиная с from_offset (в байтах).
        Возвращает (новый_offset, список строк).
        """
        if isinstance(date_, str):
            date_ = datetime.strptime(date_, '%Y-%m-%d').date()
        path = self.logs_dir / f"{command}_{date_.isoformat()}.log"
        if not path.exists():
            return from_offset, []

        size = path.stat().st_size
        if from_offset > size:
            from_offset = 0
        if from_offset == size:
            return from_offset, []

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(from_offset)
            data = f.read()
            new_offset = f.tell()

        lines = [line for line in data.splitlines() if line.strip()]
        return new_offset, lines
