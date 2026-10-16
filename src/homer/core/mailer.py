"""
Модуль отправки email по шаблонам.

Поддерживает несколько транспортов:
    - smtp      : через smtplib (по умолчанию)
    - mailx     : через утилиту mailx (/usr/bin/mailx, /bin/mailx)
    - sendmail  : через sendmail -t
    - file      : сохраняет письма в директорию (для отладки)

Шаблоны хранятся в директории из config.yml (mailer.templates_dir),
по умолчанию ./email.

Поддерживаемые файлы шаблона:
    email/<name>.html     — HTML-версия тела
    email/<name>.txt      — текстовая версия тела
    email/<name>.subject  — тема письма (опционально)

Плейсхолдеры в шаблонах: {{ key }} (Jinja2, если установлен,
иначе — простой встроенный рендер).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
import os
from pathlib import Path
import re
import shutil
import smtplib
import ssl
import subprocess
from typing import Any, Optional, Union

from homer.tracing import span

StrOrList = Union[str, Iterable[str]]

try:
    from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

    _HAS_JINJA = True
except ImportError:
    _HAS_JINJA = False


class MailError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════
#                            ТРАНСПОРТЫ
# ══════════════════════════════════════════════════════════════════════


class BaseTransport:
    """Базовый класс транспорта"""

    name = 'base'

    def __init__(self, config):
        self.config = config

    def send(self, msg, recipients):
        """
        msg        — email.message.Message
        recipients — список получателей
        """
        raise NotImplementedError


class SMTPTransport(BaseTransport):
    """Отправка через SMTP"""

    name = 'smtp'

    def send(self, msg, recipients):
        cfg = self.config
        host = cfg.get('host', 'localhost')
        port = cfg.get('port', 25)
        user = cfg.get('user')
        password = cfg.get('password')
        use_tls = cfg.get('use_tls', False)
        use_ssl = cfg.get('use_ssl', False)
        timeout = cfg.get('timeout', 30)

        try:
            if use_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
            else:
                server = smtplib.SMTP(host, port, timeout=timeout)
                if use_tls:
                    server.starttls(context=ssl.create_default_context())

            if user:
                server.login(user, password)

            server.sendmail(msg['From'], recipients, msg.as_string())
            server.quit()
        except Exception as e:
            raise MailError(f"SMTP error: {e}") from e


class MailxTransport(BaseTransport):
    """
    Отправка через mailx (heirloom mailx / bsd-mailx).

    Конфиг (mailer.mailx):
        binary: /usr/bin/mailx        # путь к бинарю
        extra_args: []                # дополнительные аргументы
        from_arg: "-r"                # как задать From (-r или -a)
        set_from_env: true            # использовать EMAIL / REPLYTO
    """

    name = 'mailx'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('mailer.mailx', {}) or {}

        self.binary = cfg.get('binary') or self._find_binary(
            ['mailx', 'nail', '/usr/bin/mailx', '/bin/mailx', '/usr/bin/nail']
        )
        if not self.binary:
            raise MailError("mailx (nail) not found. Specify mailer.mailx.binary in config.yml")

        self.extra_args = cfg.get('extra_args', [])
        self.from_arg = cfg.get('from_arg', '-r')
        self.set_from_env = cfg.get('set_from_env', True)

    @staticmethod
    def _find_binary(candidates):
        for c in candidates:
            path = shutil.which(c)
            if path:
                return path
            if os.path.isabs(c) and Path(c).exists():
                return c
        return None

    def send(self, msg, recipients):
        cmd = [self.binary]

        # Тема письма
        cmd += ['-s', msg['Subject']]

        # From
        from_addr = msg['From']
        if self.from_arg and from_addr:
            cmd += [self.from_arg, from_addr]

        # Дополнительные аргументы
        cmd += list(self.extra_args)

        # Получатели
        cmd += list(recipients)

        # Тело — берём самую "богатую" версию (html → txt)
        body = None
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                break
        if body is None:
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    break
        if body is None:
            body = ''

        env = os.environ.copy()
        if self.set_from_env and from_addr:
            env['EMAIL'] = from_addr
            env['REPLYTO'] = from_addr

        try:
            result = subprocess.run(
                cmd,
                input=body.encode('utf-8'),
                capture_output=True,
                env=env,
                timeout=60,
            )
            if result.returncode != 0:
                raise MailError(
                    f"mailx returned the code {result.returncode}: "
                    f"{result.stderr.decode('utf-8', errors='replace').strip()}"
                )
        except subprocess.TimeoutExpired:
            raise MailError("mailx didn’t respond within 60 seconds.")
        except FileNotFoundError:
            raise MailError(f"The mailx binary was not found: {self.binary}")


class SendmailTransport(BaseTransport):
    """
    Отправка через sendmail -t.

    Конфиг (mailer.sendmail):
        binary: /usr/sbin/sendmail
        extra_args: ["-t", "-i"]
    """

    name = 'sendmail'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get('mailer.sendmail', {}) or {}

        self.binary = cfg.get('binary') or self._find_binary(
            ['sendmail', '/usr/sbin/sendmail', '/usr/lib/sendmail']
        )
        if not self.binary:
            raise MailError("sendmail not found. Specify mailer.sendmail.binary in config.yml")

        self.extra_args = cfg.get('extra_args', ['-t', '-i'])

    @staticmethod
    def _find_binary(candidates):
        for c in candidates:
            path = shutil.which(c)
            if path:
                return path
            if os.path.isabs(c) and Path(c).exists():
                return c
        return None

    def send(self, msg, recipients):
        cmd = [self.binary] + list(self.extra_args)
        try:
            result = subprocess.run(
                cmd,
                input=msg.as_bytes(),
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise MailError(
                    f"sendmail returned the code {result.returncode}: "
                    f"{result.stderr.decode('utf-8', errors='replace').strip()}"
                )
        except subprocess.TimeoutExpired:
            raise MailError("sendmail did not respond within 60 seconds")


class FileTransport(BaseTransport):
    """
    Сохраняет письма в директорию — удобно для отладки.

    Конфиг (mailer.file):
        dir: /var/spool/homer/mail
    """

    name = 'file'

    def __init__(self, config):
        super().__init__(config)
        cfg = config.get("mailer.file", {}) or {}
        path = cfg.get("dir")

        if not path:
            paths = getattr(config, "paths", None)
            if paths:
                path = paths.email_out_dir
            else:
                path = "var/email"

        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, msg, recipients):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        path = self.dir / f"{ts}.eml"
        path.write_bytes(msg.as_bytes())
        log = self.dir / 'sent.log'
        with open(log, 'a', encoding='utf-8') as f:
            f.write(f"{ts}\t{msg['Subject']}\t{', '.join(recipients)}\t{path.name}\n")


# Регистр транспортов
TRANSPORTS = {
    'smtp': SMTPTransport,
    'mailx': MailxTransport,
    'sendmail': SendmailTransport,
    'file': FileTransport,
}


# ══════════════════════════════════════════════════════════════════════
#                              MAILER
# ══════════════════════════════════════════════════════════════════════


class Mailer:
    def __init__(self, config, templates_dir=None, extra_template_dirs=None):
        """
        config        — объект Config
        templates_dir — директория шаблонов (по умолчанию из конфига или ./email)
        """
        self.config = config

        if templates_dir is None:
            paths = getattr(config, "paths", None)
            if paths:
                templates_dir = paths.email_templates_dir
            else:
                templates_dir = config.get("mailer.templates_dir", "email")

        self.templates_dir = Path(templates_dir)

        search_dirs = [self.templates_dir]
        if extra_template_dirs:
            search_dirs.extend(extra_template_dirs)

        if _HAS_JINJA:
            loader = ChoiceLoader(
                [FileSystemLoader(str(d)) for d in search_dirs if Path(d).exists()]
            )
            self._jinja_env = Environment(
                loader=loader,
                autoescape=select_autoescape(['html', 'xml']),
                trim_blocks=True,
                lstrip_blocks=True,
            )

        self.default_from = config.get('mailer.from', 'homer@localhost')
        self.default_from_name = config.get('mailer.from_name', 'Homer')

        # Выбираем транспорт
        transport_name = config.get('mailer.transport', 'smtp')
        if transport_name not in TRANSPORTS:
            raise MailError(
                f"Unknown transport '{transport_name}'. Available: {', '.join(TRANSPORTS)}"
            )
        self.transport_name = transport_name
        self.transport = TRANSPORTS[transport_name](config)

        # Jinja2
        self._jinja_env = None
        if _HAS_JINJA and self.templates_dir.exists():
            self._jinja_env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=select_autoescape(['html', 'xml']),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            # Полезные фильтры для писем
            self._jinja_env.filters['num'] = self._fmt_number
            self._jinja_env.filters['dt'] = self._fmt_date
            # Глобальные переменные
            self._jinja_env.globals['app_name'] = config.get('app.name', 'Homer')
            self._jinja_env.globals['app_version'] = config.get('app.version', '1.0')

    # ─────────────────── Фильтры ───────────────────

    @staticmethod
    def _fmt_number(value):
        try:
            return f"{int(value):,}".replace(',', ' ')
        except (ValueError, TypeError):
            return value

    @staticmethod
    def _fmt_date(value, fmt='%d.%m.%Y %H:%M'):
        if hasattr(value, 'strftime'):
            return value.strftime(fmt)
        return value

    # ─────────────────── Шаблоны ───────────────────

    def _load_template(self, name, ext):
        path = self.templates_dir / f"{name}.{ext}"
        if not path.exists():
            return None
        return path.read_text(encoding='utf-8')

    def _render(self, template_str, context):
        if template_str is None:
            return None

        if self._jinja_env is not None:
            return self._jinja_env.from_string(template_str).render(**context)

        def replace(match):
            key = match.group(1).strip()
            if '|' in key:
                key, _, default = key.partition('|')
                key = key.strip()
                default = default.strip().strip('"\'')
                return str(context.get(key, default))
            return str(context.get(key, match.group(0)))

        return re.sub(r'\{\{\s*([^}]+?)\s*\}\}', replace, template_str)

    def render(
        self,
        template_name: str,
        context: Optional[dict[str, Any]] = None,
        subject_override: Optional[str] = None,
    ) -> dict[str, Optional[str]]:
        context = context or {}

        html = self._load_template(template_name, 'html')
        text = self._load_template(template_name, 'txt')
        subject_tpl = self._load_template(template_name, 'subject')

        if html is None and text is None:
            raise MailError(f"Шаблон '{template_name}' не найден в {self.templates_dir}")

        result = {
            'html': self._render(html, context) if html else None,
            'text': self._render(text, context) if text else None,
        }

        if subject_override is not None:
            result['subject'] = subject_override
        elif subject_tpl:
            result['subject'] = self._render(subject_tpl, context).strip()
        else:
            result['subject'] = self.config.get('mailer.default_subject', 'Notification Homer')

        return result

    # ─────────────────── Отправка ───────────────────

    def send(
        self,
        to: StrOrList,
        template_name: str,
        context: Optional[dict[str, Any]] = None,
        subject: Optional[str] = None,
        cc: Optional[StrOrList] = None,
        bcc: Optional[StrOrList] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[Iterable[Union[str, Path]]] = None,
        from_addr: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> bool:
        with span(
            'mailer.send',
            kind='client',
            attributes={
                'mailer.transport': self.transport_name,
                'mailer.template': template_name,
                'mailer.to': ', '.join(self._as_list(to))[:200],
                'mailer.subject': subject or '',
            },
        ):
            rendered = self.render(template_name, context, subject_override=subject)

            msg = MIMEMultipart('mixed')
            msg['Subject'] = rendered['subject']
            msg['From'] = formataddr(
                (
                    from_name or self.default_from_name,
                    from_addr or self.default_from,
                )
            )
            msg['To'] = ', '.join(self._as_list(to))
            msg['Date'] = formatdate(localtime=True)
            msg['Message-ID'] = make_msgid()

            if cc:
                msg['Cc'] = ', '.join(self._as_list(cc))
            if reply_to:
                msg['Reply-To'] = reply_to

            body = MIMEMultipart('alternative')
            if rendered['text']:
                body.attach(MIMEText(rendered['text'], 'plain', 'utf-8'))
            if rendered['html']:
                body.attach(MIMEText(rendered['html'], 'html', 'utf-8'))
            msg.attach(body)

            if attachments:
                for path in attachments:
                    path = Path(path)
                    if not path.exists():
                        raise MailError(f"The attachment was not found: {path}")
                    part = MIMEApplication(path.read_bytes(), Name=path.name)
                    part['Content-Disposition'] = f'attachment; filename="{path.name}"'
                    msg.attach(part)

            recipients = self._as_list(to) + self._as_list(cc) + self._as_list(bcc)
            self.transport.send(msg, recipients)
            return True

    def _as_list(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)

    # ─────────────────── Утилиты ───────────────────

    def list_templates(self) -> list[str]:
        if not self.templates_dir.exists():
            return []
        names = set()
        for f in self.templates_dir.iterdir():
            if f.suffix in ('.html', '.txt', '.subject'):
                names.add(f.stem)
        # Также подхватываем шаблоны в подпапках (notifications/ и т.п.)
        for f in self.templates_dir.rglob('*'):
            if f.is_file() and f.suffix in ('.html', '.txt', '.subject'):
                rel = f.relative_to(self.templates_dir)
                names.add(str(rel.with_suffix('')))
        return sorted(names)

    def check(self) -> tuple[bool, str]:
        """Проверка доступности транспорта. Возвращает (ok, message)"""
        try:
            if isinstance(self.transport, MailxTransport):
                return True, f"mailx: {self.transport.binary}"
            if isinstance(self.transport, SendmailTransport):
                return True, f"sendmail: {self.transport.binary}"
            if isinstance(self.transport, FileTransport):
                return True, f"file: {self.transport.dir}"
            if isinstance(self.transport, SMTPTransport):
                cfg = self.config.get('mailer.smtp', {}) or {}
                return True, f"smtp: {cfg.get('host')}:{cfg.get('port')}"
        except Exception as e:
            return False, str(e)
        return True, self.transport_name
