"""
Менеджер фоновых сервисов Homer (webui, scheduler и т.д.).

Как pg_ctl:
    start    — запустить в фоне, записать PID в var/<svc>.pid
    stop     — послать SIGTERM, дождаться завершения
    restart  — stop + start
    reload   — послать SIGHUP (перечитать конфиг без перезапуска)
    status   — показать состояние процесса

Кроссплатформенность:
    Unix    — os.fork + setsid
    Windows — subprocess.Popen с DETACHED_PROCESS

PID-файл:   var/<service>.pid
Лог:        var/<service>.log
"""
from __future__ import annotations

import errno
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from homer.core.paths import run_dir, cache_dir, ensure, log_dir

class ServiceStatus:
    RUNNING   = 'running'
    STOPPED   = 'stopped'
    STALE     = 'stale'      # PID есть, но процесса нет
    STARTING  = 'starting'
    STOPPING  = 'stopping'
    UNKNOWN   = 'unknown'


@dataclass
class ServiceState:
    name: str
    status: str
    pid: Optional[int] = None
    uptime: Optional[float] = None
    pid_file: Optional[Path] = None
    log_file: Optional[Path] = None
    started_at: Optional[datetime] = None
    message: str = ''


class ServiceManager:
    def __init__(self, root_dir: Path, service_name: str, config=None):
        self.root = Path(root_dir)
        self.name = service_name
        self.config = config

        paths = getattr(config, "paths", None) if config else None

        if paths:
            self.run_dir = paths.run_dir
            self.cache_dir = paths.cache_dir
            self.log_dir = paths.log_dir
        else:
            self.run_dir = run_dir(config, self.root)
            self.cache_dir = cache_dir(config, self.root)
            self.log_dir = log_dir(config, self.root)

        for d in (self.run_dir, self.cache_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.pid_file = self.run_dir / f'{service_name}.pid'
        self.meta_file = self.cache_dir / f'{service_name}.meta.json'
        # Лог сервиса теперь в var/log/<service>/<date>.log — см. webui_service
        # Для совместимости оставим старую ссылку, но она будет
        # перенаправлена в актуальный путь ниже
        self.log_file = self._resolve_service_log_file()

    def _resolve_service_log_file(self) -> Path:
        from datetime import date
        # Для сервисов пишем лог в var/log/<service>/<date>.log
        d = ensure(log_dir(self.config, self.root) / self.name)
        return d / f"{date.today().isoformat()}.log"

    # ─────────── Информация ───────────

    def read_pid(self) -> Optional[int]:
        if not self.pid_file.exists():
            return None
        try:
            text = self.pid_file.read_text(encoding='utf-8').strip()
            return int(text)
        except (ValueError, OSError):
            return None

    def is_alive(self, pid: int) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            if e.errno == errno.ESRCH:
                return False  # нет такого процесса
            if e.errno == errno.EPERM:
                return True   # есть, но чужой
            return False

    def read_meta(self) -> dict:
        if not self.meta_file.exists():
            return {}
        try:
            return json.loads(self.meta_file.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def write_meta(self, data: dict):
        self.meta_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def status(self) -> ServiceState:
        pid = self.read_pid()
        meta = self.read_meta()

        if pid is None:
            return ServiceState(
                name=self.name, status=ServiceStatus.STOPPED,
                pid_file=self.pid_file, log_file=self.log_file,
            )

        if not self.is_alive(pid):
            return ServiceState(
                name=self.name, status=ServiceStatus.STALE,
                pid=pid,
                pid_file=self.pid_file, log_file=self.log_file,
                message='PID есть, но процесса нет (stale PID-файл)',
            )

        started_at = None
        uptime = None
        if meta.get('started_at'):
            try:
                started_at = datetime.fromisoformat(meta['started_at'])
                uptime = (datetime.now() - started_at).total_seconds()
            except Exception:
                pass

        return ServiceState(
            name=self.name, status=ServiceStatus.RUNNING,
            pid=pid,
            pid_file=self.pid_file, log_file=self.log_file,
            started_at=started_at, uptime=uptime,
            message=meta.get('message', ''),
        )

    # ─────────── Start ───────────

    def start(self, argv: list[str], *, force: bool = False) -> ServiceState:
        """
        Запускает сервис в фоне.
        argv — командная строка дочернего процесса (без fork; полный список).
        """
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        st = self.status()
        if st.status == ServiceStatus.RUNNING and not force:
            return st  # уже запущен

        if st.status in (ServiceStatus.STALE, ServiceStatus.RUNNING) and force:
            # Попробуем сначала остановить
            self.stop(timeout=5, force=True)

        # Готовим лог
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        if sys.platform == 'win32':
            return self._start_windows(argv)
        return self._start_unix(argv)

    def _start_unix(self, argv: list[str]) -> ServiceState:
        """Двойной fork + setsid → демон."""
        # Файл для передачи ошибок от дочернего процесса
        err_pipe_r, err_pipe_w = os.pipe()

        pid = os.fork()
        if pid > 0:
            # Родитель: ждём, пока ребёнок скажет, что стартовал
            os.close(err_pipe_w)
            with os.fdopen(err_pipe_r, 'rb', closefd=True) as r:
                data = r.read()
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass

            if data:
                raise RuntimeError(data.decode('utf-8', errors='replace'))

            time.sleep(0.3)
            return self.status()

        # ─── Ребёнок 1 ───
        try:
            os.setsid()
        except OSError:
            pass

        pid2 = os.fork()
        if pid2 > 0:
            os._exit(0)

        # ─── Ребёнок 2 (реальный сервис) ───
        try:
            # Стандартные потоки → /dev/null, лог пишем сами
            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 0)
            # stdout/stderr → лог
            log_fd = os.open(
                str(self.log_file),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
            os.close(log_fd)

            # Меняем рабочий каталог
            os.chdir(str(self.root))

            # Пишем свой PID
            self.pid_file.write_text(str(os.getpid()), encoding='utf-8')

            # meta
            self.write_meta({
                'started_at': datetime.now().isoformat(),
                'argv': argv,
                'cwd': str(self.root),
            })

            # Запускаем сервис
            # Используем os.execvp — процесс заменится
            os.execvp(argv[0], argv)
        except Exception as e:
            # Сообщаем родителю
            try:
                os.write(err_pipe_w, str(e).encode('utf-8'))
            except Exception:
                pass
            os._exit(1)

    def _start_windows(self, argv: list[str]) -> ServiceState:
        """Windows: subprocess.Popen с DETACHED_PROCESS."""
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200

        log = open(self.log_file, 'ab')
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self.root),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        finally:
            log.close()

        self.pid_file.write_text(str(proc.pid), encoding='utf-8')
        self.write_meta({
            'started_at': datetime.now().isoformat(),
            'argv': argv,
            'cwd': str(self.root),
        })
        time.sleep(0.3)
        return self.status()

    # ─────────── Stop ───────────

    def stop(self, timeout: float = 10.0, force: bool = False
             ) -> ServiceState:
        st = self.status()
        if st.status in (ServiceStatus.STOPPED, ServiceStatus.STALE):
            # Стираем stale pid
            try:
                self.pid_file.unlink()
            except FileNotFoundError:
                pass
            return ServiceState(name=self.name, status=ServiceStatus.STOPPED,
                                pid_file=self.pid_file, log_file=self.log_file)

        pid = st.pid
        # Сигнал
        try:
            if sys.platform == 'win32':
                os.kill(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError as e:
            if e.errno != errno.ESRCH:
                raise

        # Ждём завершения
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_alive(pid):
                break
            time.sleep(0.1)

        # Если всё ещё жив — SIGKILL
        if self.is_alive(pid):
            try:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                   capture_output=True)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.2)

        # Убираем файлы
        for f in (self.pid_file, self.meta_file):
            try:
                f.unlink()
            except FileNotFoundError:
                pass

        return ServiceState(name=self.name, status=ServiceStatus.STOPPED,
                            pid_file=self.pid_file, log_file=self.log_file)

    # ─────────── Restart ───────────

    def restart(self, argv: list[str], *, timeout: float = 10.0
                ) -> ServiceState:
        self.stop(timeout=timeout)
        time.sleep(0.5)
        return self.start(argv, force=True)

    # ─────────── Reload (SIGHUP) ───────────

    def reload(self) -> ServiceState:
        st = self.status()
        if st.status != ServiceStatus.RUNNING:
            return st

        try:
            if sys.platform == 'win32':
                # На Windows SIGHUP нет — шлём SIGBREAK (обрабатывается)
                os.kill(st.pid, signal.SIGBREAK)
            else:
                os.kill(st.pid, signal.SIGHUP)
        except OSError as e:
            st.message = f"SIGHUP не отправлен: {e}"

        return st
