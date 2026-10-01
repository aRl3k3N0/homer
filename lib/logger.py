"""
Логирование с разделением по дням и командам.
"""
import json
import logging
import sys
from pathlib import Path
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Форматтер, пишущий JSON-строки — идеально для Loki/ELK."""

    def __init__(self, command=None):
        super().__init__()
        self.command = command

    def format(self, record):
        payload = {
            'ts': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'command': self.command or 'default',
            'msg': record.getMessage(),
            'module': record.module,
            'func': record.funcName,
            'line': record.lineno,
        }
        # Дополнительные поля из extra
        for k, v in record.__dict__.items():
            if k.startswith('homer_'):
                payload[k[6:]] = v
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Классический текстовый формат — как раньше."""

    def __init__(self):
        super().__init__(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )


class Logger:
    def __init__(self, config, logs_dir):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(exist_ok=True, parents=True)
        self.config = config
        self._loggers = {}

        log_config = config.get('logging', {}) or {}
        self.log_level = getattr(logging, log_config.get('level', 'INFO').upper())
        self.console_output = log_config.get('console', True)
        self.format = log_config.get('format', 'text')  # text | json

    def _get_logger(self, command=None):
        key = (command or 'default').replace(':', '_')
        if key in self._loggers:
            return self._loggers[key]

        logger = logging.getLogger(f'homer.{key}')
        logger.setLevel(self.log_level)
        logger.handlers = []
        logger.propagate = False

        # Форматтер
        if self.format == 'json':
            formatter = JSONFormatter(command=command)
        else:
            formatter = logging.Formatter(
                '[%(asctime)s] | %(levelname)-8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
            )

        date_str = datetime.now().strftime('%Y-%m-%d')
        log_path = self.logs_dir / f"{key}_{date_str}.log"

        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(console_handler)

        self._loggers[key] = logger
        return logger

    def info(self, message, command=None, **extra):
        self._log_with_extra('info', message, command, extra)

    def debug(self, message, command=None, **extra):
        self._log_with_extra('debug', message, command, extra)

    def warning(self, message, command=None, **extra):
        self._log_with_extra('warning', message, command, extra)

    def error(self, message, command=None, exc_info=False, **extra):
        self._get_logger(command).error(
            message, exc_info=exc_info, extra=self._extra(extra),
        )

    def critical(self, message, command=None, **extra):
        self._log_with_extra('critical', message, command, extra)

    def _log_with_extra(self, level, message, command, extra):
        from lib.tracing import get_current_trace_id, get_current_span_id
        tid = get_current_trace_id()
        sid = get_current_span_id()
        if tid:
            extra.setdefault('trace_id', tid)
        if sid:
            extra.setdefault('span_id', sid)
        logger = self._get_logger(command)
        getattr(logger, level)(message, extra=self._extra(extra))

    @staticmethod
    def _extra(extra):
        # Префикс homer_ защищает от конфликта с зарезервированными полями
        return {f'homer_{k}': v for k, v in extra.items()}
