"""
Homer logger.

Wraps the standard logging module and adds:
    - per-command routing:  var/log/<command>/<YYYY-MM-DD>.log
    - automatic date-based file rotation
    - optional JSON output
    - support for %-style messages (like the built-in logging module)
    - extra structured fields prefixed with `homer_`

Public API is compatible with logging.Logger but `command` is
keyword-only. Pass extra context as keyword arguments.

Examples:
    logger.info("plain", command="webui")
    logger.info("value is %s", value, command="webui")
    logger.error("failed: %s", e, command="webui", exc_info=True)
    logger.info("user did something", command="webui", user_id=7)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from lib.paths import log_dir, ensure


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


class JSONFormatter(logging.Formatter):
    def __init__(self, command: str | None = None):
        super().__init__()
        self.command = command

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "command": self.command or "default",
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        for k, v in record.__dict__.items():
            if k.startswith("homer_"):
                payload[k[6:]] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class Logger:
    def __init__(self, config, root_dir):
        self.config = config
        self.root_dir = Path(root_dir)

        log_config = config.get("logging", {}) or {}
        self.log_level = getattr(
            logging, log_config.get("level", "INFO").upper(),
        )
        self.console_output = log_config.get("console", True)
        self.format = log_config.get("format", "text")

        # Prefer paths from config if available
        paths = getattr(config, "paths", None)
        if paths:
            self.base_dir = paths.log_dir
        else:
            from lib.paths import log_dir, ensure
            self.base_dir = ensure(log_dir(config, root_dir))
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._loggers: dict[str, logging.Logger] = {}
        self._fdates: dict[str, date] = {}

    # ─────────── Path helpers ───────────

    @staticmethod
    def _safe_name(command: str | None) -> str:
        return (command or "default").replace(":", "_").replace("/", "_")

    def _command_dir(self, command: str | None) -> Path:
        d = self.base_dir / self._safe_name(command)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _log_path(self, command: str | None, on_date: date | None = None) -> Path:
        on_date = on_date or date.today()
        return self.base_dir / self._safe_name(command) / f"{on_date.isoformat()}.log"

    # ─────────── Logger construction ───────────

    def _get_logger(self, command: str | None = None) -> logging.Logger:
        key = self._safe_name(command)
        today = date.today()

        need_reopen = (
            key not in self._loggers
            or self._fdates.get(key) != today
        )
        if not need_reopen:
            return self._loggers[key]

        logger = logging.getLogger(f"homer.{key}")
        logger.setLevel(self.log_level)
        logger.handlers = []
        logger.propagate = False

        if self.format == "json":
            file_formatter: logging.Formatter = JSONFormatter(command=command)
        else:
            file_formatter = TextFormatter()

        path = self._log_path(command, today)
        path.parent.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)

        if self.console_output:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(TextFormatter())
            logger.addHandler(ch)

        self._loggers[key] = logger
        self._fdates[key] = today
        return logger

    # ─────────── Core ───────────

    def _log(
        self,
        level: str,
        message,
        *args,
        command: str | None = None,
        exc_info: bool = False,
        **extra,
    ) -> None:
        """
        Forward to logging.Logger.<level>.

        Accepts:
            logger.info("plain")
            logger.info("with %s", value)
            logger.info("with %s and %s", a, b)
            logger.info("plain", command="cmd", user_id=1)
            logger.error("failed: %s", e, command="cmd", exc_info=True)
        """
        logger = self._get_logger(command)
        extra_clean = {f"homer_{k}": v for k, v in extra.items() if v is not None}

        try:
            if args:
                getattr(logger, level)(
                    message, *args, exc_info=exc_info, extra=extra_clean,
                )
            else:
                getattr(logger, level)(
                    message, exc_info=exc_info, extra=extra_clean,
                )
        except (TypeError, ValueError):
            # Message had unescaped % — fall back to plain string.
            getattr(logger, level)(
                str(message), exc_info=exc_info, extra=extra_clean,
            )

    # ─────────── Public levels ───────────

    def debug(self, message, *args, command: str | None = None, **extra) -> None:
        self._log("debug", message, *args, command=command, **extra)

    def info(self, message, *args, command: str | None = None, **extra) -> None:
        self._log("info", message, *args, command=command, **extra)

    def warning(self, message, *args, command: str | None = None, **extra) -> None:
        self._log("warning", message, *args, command=command, **extra)

    def error(
        self,
        message,
        *args,
        command: str | None = None,
        exc_info: bool = False,
        **extra,
    ) -> None:
        self._log("error", message, *args, command=command,
                  exc_info=exc_info, **extra)

    def critical(self, message, *args, command: str | None = None, **extra) -> None:
        self._log("critical", message, *args, command=command, **extra)

    # ─────────── Introspection ───────────

    def list_files(self) -> list[Path]:
        if not self.base_dir.exists():
            return []
        return sorted(self.base_dir.rglob("*.log"), reverse=True)
