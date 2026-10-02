"""
Асинхронный планировщик+воркер на asyncio.

Использование:
    from lib.scheduler.async_runner import AsyncScheduler
    sched = AsyncScheduler(...)
    asyncio.run(sched.run_loop(interval=30))

Отличия от синхронного Scheduler:
    - воркеры — asyncio.Task, не потоки;
    - I/O (БД, HTTP, email) не блокируют event loop;
    - если команда написана синхронно — запускается через run_in_executor;
    - если команда — async def execute_async(context) — выполняется напрямую.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import traceback

from lib.queue import QueueStorage
from lib.queue.models import JobStatus, QueueJob


class AsyncScheduler:
    def __init__(
        self,
        storage,
        command_loader,
        config,
        logger,
        root_dir,
        lease_seconds=300,
        max_workers=8,
        heartbeat_interval=30,
        notify_manager=None,
    ):
        self.storage = storage
        self.queue = QueueStorage(config)
        self.command_loader = command_loader
        self.config = config
        self.logger = logger
        self.root_dir = root_dir
        self.notify_manager = notify_manager

        self.lease_seconds = lease_seconds
        self.max_workers = max_workers
        self.heartbeat_interval = heartbeat_interval

        self._semaphore = asyncio.Semaphore(max_workers)
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    def stop(self):
        self._stop.set()

    async def run_loop(self, interval=30):
        self.logger.info(f"[asyncio] Старт, воркеров={self.max_workers}")
        print(f"⚡ Async scheduler запущен. Воркеров: {self.max_workers}, интервал: {interval}с")

        try:
            while not self._stop.is_set():
                await self._cycle()
                # Ждём interval или stop
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            # Дождёмся активных задач (или отменим)
            if self._tasks:
                print("Ждём завершения активных задач...")
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _cycle(self):
        try:
            self.tick()
            await self.process_queue()
        except Exception as e:
            self.logger.error(f"[asyncio] Ошибка цикла: {e}", exc_info=True)

    # ─────────── Cron → очередь (синхронный, лёгкий) ───────────

    def tick(self):
        from lib.scheduler.cron import CronExpression

        now = datetime.now().replace(second=0, microsecond=0)
        tasks = self.storage.list()

        for task in tasks:
            if not task.enabled:
                continue
            try:
                cron = CronExpression(task.cron)
            except ValueError as e:
                self.logger.error(f"Плохое cron '{task.name}': {e}")
                continue
            if not cron.matches(now):
                continue
            if (
                task.last_run
                and task.last_run.replace(second=0, microsecond=0) == now
                and task.last_status != JobStatus.RUNNING
            ):
                continue
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
            self.logger.info(f"[asyncio] '{task.name}' → queue job #{job_id}")
            self.storage.release_task(task.id, run_id, status='running')

    # ─────────── Очередь → выполнение ───────────

    async def process_queue(self):
        free_slots = self.max_workers - len(self._tasks)
        if free_slots <= 0:
            return

        for _ in range(free_slots):
            job = self.queue.acquire_next(self.lease_seconds)
            if job is None:
                break

            task = asyncio.create_task(self._run_job(job))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_job(self, job: QueueJob):
        async with self._semaphore:
            stop_hb = asyncio.Event()

            async def heartbeat():
                while not stop_hb.is_set():
                    try:
                        await asyncio.wait_for(stop_hb.wait(), timeout=self.heartbeat_interval)
                        return
                    except asyncio.TimeoutError:
                        pass
                    ok = self.queue.heartbeat(
                        job.id,
                        job.run_id,
                        self.lease_seconds,
                    )
                    if not ok:
                        self.logger.warning(f"[asyncio] Потеряна аренда job #{job.id}")
                        return

            hb_task = asyncio.create_task(heartbeat())

            status = JobStatus.DONE
            error = None
            output = None
            exit_code = 0

            try:
                self.logger.info(f"[asyncio] job #{job.id}: {job.command}")
                exit_code, output = await self._execute_async(job)
                if exit_code != 0:
                    status = JobStatus.FAILED
                    error = f"exit code {exit_code}"
            except Exception as e:
                status = JobStatus.FAILED
                error = f"{e}\n{traceback.format_exc()[:3000]}"
                exit_code = 1
                self.logger.error(f"[asyncio] job #{job.id} failed: {e}", exc_info=True)
            finally:
                stop_hb.set()
                hb_task.cancel()
                try:
                    await hb_task
                except (asyncio.CancelledError, Exception):
                    pass

                # Обрезаем
                if output and len(output) > 100_000:
                    output = output[:100_000] + "\n...[truncated]"

                self.queue.finish(
                    job.id,
                    job.run_id,
                    status,
                    result=output,
                    exit_code=exit_code,
                    error=error,
                )

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
                        self.logger.error(f"[notify] {e}", exc_info=True)

                self.logger.info(f"[asyncio] job #{job.id} → {status} (exit={exit_code})")

    async def _execute_async(self, job: QueueJob):
        """Запускает execute либо как async-корутину, либо в executor."""
        import contextlib
        import io

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

        ctx = {
            'config': self.config,
            'logger': self.logger,
            'args': parser.options,
            'root_dir': self.root_dir,
            'command_name': cmd_name,
            'cancel_check': cancel_check,
        }

        from lib.queue import Dispatcher

        ctx['queue'] = Dispatcher(
            self.queue,
            config=self.config,
            triggered_by=f"job#{job.id}",
        )

        module = commands[cmd_name].get('module')
        execute = commands[cmd_name]['execute']

        # Приоритет: async def execute_async(context)
        if module and hasattr(module, 'execute_async'):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = await module.execute_async(ctx)
            return (0 if result in (None, 0, True) else int(result or 0), buf.getvalue())

        # Иначе — синхронный execute в отдельном потоке
        loop = asyncio.get_running_loop()

        def _run_sync():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                result = execute(ctx)
            return (0 if result in (None, 0, True) else int(result or 0), buf.getvalue())

        return await loop.run_in_executor(None, _run_sync)
