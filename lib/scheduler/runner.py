"""
Планировщик + воркеры очереди.

Поддерживает три режима выполнения: threads, processes, subprocess.

Управление:
    scheduler = Scheduler(...)
    scheduler.run_loop(interval=30)
    # из другого потока/сигнала:
    scheduler.stop()
"""

from __future__ import annotations

import contextlib
import io
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import multiprocessing as mp

from lib.metrics import (
    get_metrics,
    inc_error,
    observe_job,
)
from lib.queue import Dispatcher, QueueStorage
from lib.queue.models import JobStatus, QueueJob
from lib.tracing import get_current_trace_id, span


class Scheduler:
    def __init__(
        self,
        storage,
        command_loader,
        config,
        logger,
        root_dir,
        lease_seconds: int = 300,
        max_workers: int = 4,
        heartbeat_interval: int = 30,
        execution_mode: str = 'threads',
        config_path=None,
        notify_manager=None,
        job_timeout_sec=None,
    ):
        self.storage = storage
        self.queue = QueueStorage(config)
        self.command_loader = command_loader
        self.config = config
        self.logger = logger
        paths = getattr(config, "paths", None)
        self.root_dir = Path(root_dir)
        if paths:
            self.root_dir = paths.base
        self.notify_manager = notify_manager

        self.lease_seconds = int(lease_seconds)
        self.max_workers = int(max_workers)
        self.heartbeat_interval = int(heartbeat_interval)
        self.execution_mode = execution_mode
        self.config_path = Path(config_path or config.config_path)
        self.job_timeout_sec = int(
            job_timeout_sec
            or (config.get('scheduler', {}) or {}).get('job_timeout_sec', 3600)
        )

        # Метрики — инициализируем ДО первого использования
        self.metrics = get_metrics()

        self._stop = threading.Event()
        self._semaphore = threading.Semaphore(self.max_workers)
        self._threads: list[threading.Thread] = []
        self._subprocesses: dict[int, subprocess.Popen] = {}
        self._subprocess_lock = threading.Lock()
        self._reload_requested = False

        self._executor: ProcessPoolExecutor | None = None
        if execution_mode == 'processes':
            ctx = mp.get_context('spawn')
            self._executor = ProcessPoolExecutor(
                max_workers=self.max_workers,
                mp_context=ctx,
            )

        # SIGHUP → перезагрузка плагинов (на Unix)
        self._install_sighup()

    # ─────────────────── Остановка ───────────────────

    def stop(self):
        self._stop.set()
        with self._subprocess_lock:
            for jid, proc in list(self._subprocesses.items()):
                try:
                    proc.terminate()
                except Exception:
                    pass
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=False)

    # ─────────────────── SIGHUP ───────────────────

    def _install_sighup(self):
        if not hasattr(signal, 'SIGHUP'):
            return
        try:
            def _on_hup(signum, frame):
                self._reload_requested = True
                self.logger.info("[scheduler] SIGHUP — запрошена перезагрузка")
            signal.signal(signal.SIGHUP, _on_hup)
        except Exception:
            pass

    def _do_reload_plugins(self):
        try:
            from lib.plugins import get_manager
            from lib.plugins.reload import PluginReloader

            mgr = get_manager()
            reloader = PluginReloader(
                mgr,
                root_dir=self.root_dir,
                config=self.config,
                homer_context={
                    'config': self.config,
                    'logger': self.logger,
                    'root_dir': self.root_dir,
                },
            )
            results = reloader.reload_all()
            for name, ok in results.items():
                if ok:
                    self.logger.info(f"[scheduler] плагин '{name}' перезагружен")
                else:
                    self.logger.error(f"[scheduler] ошибка reload '{name}'")
        except Exception as e:
            self.logger.error(f"[scheduler] reload: {e}", exc_info=True)

    # ─────────────────── Главный цикл ───────────────────

    def run_loop(self, interval: int = 30):
        self.logger.info(
            f"[scheduler] Старт (mode={self.execution_mode}, "
            f"workers={self.max_workers}, lease={self.lease_seconds}с)"
        )
        print(
            f"⏱  Scheduler+Worker запущен. Режим: {self.execution_mode}, "
            f"воркеров: {self.max_workers}, интервал: {interval}с"
        )

        try:
            while not self._stop.is_set():
                # Обработка отложенного reload
                if self._reload_requested:
                    self._reload_requested = False
                    self._do_reload_plugins()

                try:
                    self.tick()
                    self.process_queue()
                except Exception as e:
                    self.logger.error(
                        f"[scheduler] Ошибка в цикле: {e}", exc_info=True,
                    )
                    inc_error('scheduler')

                # Чистим завершённые треды
                self._threads = [t for t in self._threads if t.is_alive()]

                # Спим короткими интервалами, чтобы быстро реагировать на stop
                for _ in range(int(interval)):
                    if self._stop.is_set():
                        break
                    time.sleep(1)

        except KeyboardInterrupt:
            print()
            self.logger.info("[scheduler] Остановлен пользователем")

        finally:
            # Ждём завершения активных задач
            deadline = time.time() + 30
            for t in self._threads:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                t.join(timeout=remaining)

    # ─────────────────── Cron → очередь ───────────────────

    def tick(self):
        from lib.scheduler.cron import CronExpression

        # Метрики tick
        try:
            self.metrics.scheduler_ticks.inc()
            self.metrics.scheduler_last_tick.set(time.time())
        except Exception:
            pass

        now = datetime.now().replace(second=0, microsecond=0)
        tasks = self.storage.list()

        for task in tasks:
            if not task.enabled:
                continue

            try:
                cron = CronExpression(task.cron)
            except ValueError as e:
                self.logger.error(
                    f"[scheduler] Плохое cron-выражение '{task.name}': {e}"
                )
                continue

            if not cron.matches(now):
                continue

            # Защита от повторного запуска в ту же минуту
            if (
                task.last_run
                and task.last_run.replace(second=0, microsecond=0) == now
                and task.last_status != JobStatus.RUNNING
            ):
                continue

            # Атомарный захват cron-задачи (только один инстанс её возьмёт)
            if not self.storage.acquire_task(task.id, self.lease_seconds):
                continue

            run_id = self.storage._current_run_id.get(task.id)
            job_id = self.queue.push(
                QueueJob(
                    command=task.command,
                    args=task.args or {},
                    priority=50,
                    triggered_by=f"cron:{task.name}",
                )
            )

            self.logger.info(f"[scheduler] '{task.name}' → queue job #{job_id}")

            # Cron-запись — в running; финал обновится в _finalize_job
            try:
                self.storage.release_task(task.id, run_id, status='running')
            except Exception as e:
                self.logger.error(
                    f"[scheduler] release_task '{task.name}': {e}"
                )

    # ─────────────────── Обработка очереди ───────────────────

    def process_queue(self):
        available = self._available_slots()
        if available <= 0:
            return

        for _ in range(available):
            job = self.queue.acquire_next(self.lease_seconds)
            if job is None:
                return

            if not self._semaphore.acquire(blocking=False):
                # Нет слота — вернуть job в pending (не терять)
                self.queue.finish(
                    job.id,
                    job.run_id,
                    JobStatus.FAILED,
                    error="не удалось получить слот воркера",
                )
                return

            if self.execution_mode == 'processes' and self._executor:
                self._submit_to_process_pool(job)
            elif self.execution_mode == 'subprocess':
                t = threading.Thread(
                    target=self._run_job_subprocess,
                    args=(job,), daemon=True,
                    name=f'homer-sub-{job.id}',
                )
                t.start()
                self._threads.append(t)
            else:
                t = threading.Thread(
                    target=self._run_job_threaded,
                    args=(job,), daemon=True,
                    name=f'homer-job-{job.id}',
                )
                t.start()
                self._threads.append(t)

    def _available_slots(self) -> int:
        active = len([t for t in self._threads if t.is_alive()])
        with self._subprocess_lock:
            active += len(self._subprocesses)
        return max(0, self.max_workers - active)

    # ─────────────────── Threads-режим ───────────────────

    def _run_job_threaded(self, job: QueueJob):
        with span(
            'job.run',
            kind='consumer',
            attributes={
                'job.id': job.id,
                'job.command': job.command,
                'job.triggered_by': job.triggered_by or '',
                'job.attempt': job.attempts,
                'job.parent_id': job.parent_job_id or 0,
            },
        ) as sp:
            stop_hb = threading.Event()

            def heartbeat_loop():
                while not stop_hb.wait(self.heartbeat_interval):
                    if not self.queue.heartbeat(
                        job.id, job.run_id, self.lease_seconds,
                    ):
                        self.logger.warning(
                            f"[queue] Потеряна аренда job #{job.id}"
                        )
                        return

            hb = threading.Thread(target=heartbeat_loop, daemon=True)
            hb.start()

            status = JobStatus.DONE
            error = None
            output = None
            exit_code = 0

            try:
                self.logger.info(f"[queue] job #{job.id}: {job.command}")
                exit_code, output = self._execute_inproc(job)
                if exit_code != 0:
                    status = JobStatus.FAILED
                    error = f"exit code {exit_code}"
            except Exception as e:
                status = JobStatus.FAILED
                error = str(e)
                exit_code = 1
                self.logger.error(
                    f"[queue] job #{job.id} failed: {e}", exc_info=True,
                )
            finally:
                stop_hb.set()

                # Атрибуты спана — независимо от успеха/ошибки
                if sp is not None:
                    try:
                        sp.set_attribute('job.status', status)
                        sp.set_attribute('job.exit_code', exit_code or 0)
                        if error:
                            sp.set_attribute('job.error', error[:500])
                        trace_id = get_current_trace_id()
                        if trace_id:
                            sp.set_attribute('trace.id', trace_id)
                    except Exception:
                        pass

                self._finalize_job(job, status, output, exit_code, error)

    def _execute_inproc(self, job: QueueJob):
        """Выполняет команду в текущем процессе, возвращает (exit_code, output)"""
        from lib.arguments import ArgumentParser

        parts = [job.command]
        for k, v in (job.args or {}).items():
            if isinstance(v, bool):
                if v:
                    parts.append(f'--{k}')
            else:
                parts.append(f'--{k}={v}')

        parser = ArgumentParser()
        parser.parse(parts)

        commands = self.command_loader.load_commands()
        try:
            from lib.commands import BUILTIN_COMMANDS
            for name, info in BUILTIN_COMMANDS.items():
                commands.setdefault(name, info)
        except Exception:
            pass

        cmd_name = parser.command
        if cmd_name not in commands:
            raise RuntimeError(f"Команда '{cmd_name}' не найдена")

        def cancel_check():
            return self.queue.is_cancel_requested(job.id)

        buf = io.StringIO()
        ctx = {
            'config': self.config,
            'logger': self.logger,
            'args': parser.options,
            'root_dir': self.root_dir,
            'command_name': cmd_name,
            'cancel_check': cancel_check,
        }
        dispatcher = Dispatcher(
            self.queue,
            config=self.config,
            triggered_by=f"job#{job.id}",
        )
        dispatcher._parent_job_id = job.id
        ctx['queue'] = dispatcher

        # Проверка отмены ДО старта
        if self.queue.is_cancel_requested(job.id):
            return 130, ''

        with contextlib.redirect_stdout(buf):
            result = commands[cmd_name]['execute'](ctx)

        exit_code = 0 if result in (None, 0, True) else int(result or 0)
        return exit_code, buf.getvalue()

    # ─────────────────── Processes-режим ───────────────────

    def _submit_to_process_pool(self, job: QueueJob):
        from lib.scheduler.process_worker import run_job_in_process

        payload = {
            'job_id': job.id,
            'command': job.command,
            'args': job.args or {},
            'triggered_by': job.triggered_by,
            'config_path': str(self.config_path),
            'root_dir': str(self.root_dir),
        }
        try:
            future = self._executor.submit(run_job_in_process, payload)
            future.add_done_callback(
                lambda f, j=job: self._on_process_done(j, f)
            )
        except Exception as e:
            self.logger.error(
                f"[queue] process pool submit error: {e}", exc_info=True,
            )
            self._finalize_job(
                job, JobStatus.FAILED, None, 1,
                f"process pool error: {e}",
            )

    def _on_process_done(self, job: QueueJob, future):
        status = JobStatus.DONE
        error = None
        exit_code = 0
        output = None

        try:
            res = future.result()
            exit_code = res['exit_code']
            output = res['output']
            if exit_code != 0:
                status = JobStatus.FAILED
                error = res['error'] or f"exit code {exit_code}"
        except Exception as e:
            status = JobStatus.FAILED
            error = f"worker crashed: {e}"
            exit_code = 1

        self._finalize_job(job, status, output, exit_code, error)

    # ─────────────────── Subprocess-режим (hard-kill) ───────────────────

    def _run_job_subprocess(self, job: QueueJob):
        """
        Запускает job в отдельном процессе через `homer _run-job`.
        Позволяет жёстко убить по таймауту.
        """
        timeout = job.timeout_sec or self.job_timeout_sec
        stop_hb = threading.Event()

        def heartbeat_loop():
            while not stop_hb.wait(self.heartbeat_interval):
                if not self.queue.heartbeat(
                    job.id, job.run_id, self.lease_seconds,
                ):
                    self.logger.warning(
                        f"[queue] Потеряна аренда job #{job.id} (subprocess)"
                    )
                    return

        hb = threading.Thread(target=heartbeat_loop, daemon=True)
        hb.start()

        env = os.environ.copy()
        env['HOMER_JOB_ID'] = str(job.id)
        env['HOMER_CONFIG'] = str(self.config_path)
        env['HOMER_ROOT_DIR'] = str(self.root_dir)

        cmd = [
            sys.executable,
            str(self.root_dir / 'homer'),
            '_run-job',
            '--id', str(job.id),
        ]

        status = JobStatus.DONE
        error = None
        exit_code = 0
        output: bytes = b''

        try:
            popen_kwargs = {
                'cwd': str(self.root_dir),
                'stdout': subprocess.PIPE,
                'stderr': subprocess.STDOUT,
                'env': env,
            }
            # start_new_session — Unix-only
            if sys.platform != 'win32':
                popen_kwargs['start_new_session'] = True

            proc = subprocess.Popen(cmd, **popen_kwargs)
            with self._subprocess_lock:
                self._subprocesses[job.id] = proc

            try:
                output, _ = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
                if exit_code in (-signal.SIGTERM, -signal.SIGKILL):
                    status = JobStatus.CANCELED
                    error = "canceled (signal)"
                elif exit_code != 0:
                    status = JobStatus.FAILED
                    error = f"exit code {exit_code}"
            except subprocess.TimeoutExpired:
                self.logger.warning(
                    f"[queue] job #{job.id} timeout {timeout}s → kill"
                )
                self._kill_process_tree(proc)
                try:
                    output, _ = proc.communicate(timeout=10)
                except Exception:
                    output = b''
                status = JobStatus.TIMEOUT
                error = f"timeout after {timeout}s"
                exit_code = 124
        except Exception as e:
            status = JobStatus.FAILED
            error = str(e)
            exit_code = 1
            self.logger.error(
                f"[queue] subprocess job #{job.id} error: {e}", exc_info=True,
            )
        finally:
            stop_hb.set()
            with self._subprocess_lock:
                self._subprocesses.pop(job.id, None)

            output_str = output.decode('utf-8', errors='replace') if output else None
            self._finalize_job(job, status, output_str, exit_code, error)

    def _kill_process_tree(self, proc: subprocess.Popen):
        """
        Убивает процесс и его группу.
        Unix  — killpg(SIGTERM) → wait → killpg(SIGKILL)
        Windows — terminate → wait → kill
        """
        if sys.platform == 'win32':
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # ─────────────────── Финализация ───────────────────

    def _finalize_job(self, job, status, output, exit_code, error):
        # Обрезаем большой вывод
        result_text = output
        if result_text and len(result_text) > 100_000:
            result_text = result_text[:100_000] + "\n...[truncated]"

        # 1) Завершаем job в очереди
        try:
            self.queue.finish(
                job.id,
                job.run_id,
                status,
                result=result_text,
                exit_code=exit_code,
                error=error,
            )
        except Exception as e:
            self.logger.error(
                f"[queue] finish #{job.id} failed: {e}", exc_info=True,
            )

        # 2) Уведомления
        if self.notify_manager:
            try:
                final = self.queue.get(job.id)
                if final and final.status in (
                    JobStatus.DONE,
                    JobStatus.FAILED,
                    JobStatus.CANCELED,
                    JobStatus.TIMEOUT,
                ):
                    self.notify_manager.emit_from_job(final)
            except Exception as e:
                self.logger.error(
                    f"[notify] emit failed: {e}", exc_info=True,
                )

        # 3) Обновляем cron-задачу (если job был порождён cron-ом)
        if job.triggered_by and job.triggered_by.startswith('cron:'):
            cron_name = job.triggered_by[len('cron:'):]
            try:
                task = self.storage.get_by_name(cron_name)
                if task and hasattr(self.storage, 'db'):
                    self.storage.db.execute(
                        f"UPDATE homer_tasks SET "
                        f"last_status = {self.storage._ph(0)}, "
                        f"last_error = {self.storage._ph(1)} "
                        f"WHERE id = {self.storage._ph(2)}",
                        [status, error, task.id],
                    )
                    self.storage.db.commit()
            except Exception as e:
                self.logger.error(
                    f"[scheduler] cron update failed: {e}", exc_info=True,
                )

        # 4) Метрики
        try:
            final = self.queue.get(job.id)
            if final:
                observe_job(final, status=status)
        except Exception as e:
            inc_error('metrics')
            self.logger.error(f"[metrics] {e}")

        # 5) Освобождаем слот — в самом конце
        try:
            self._semaphore.release()
        except Exception:
            pass

        self.logger.info(
            f"[queue] job #{job.id} → {status} (exit={exit_code})"
        )
