"""
Исполнитель задач планировщика.
"""
import time
import traceback
from datetime import datetime, timedelta

from lib.arguments import ArgumentParser


class Scheduler:
    """Планировщик: хранит задачи и исполняет их по cron"""

    def __init__(self, storage, command_loader, config, logger, root_dir):
        self.storage = storage
        self.command_loader = command_loader
        self.config = config
        self.logger = logger
        self.root_dir = root_dir
        self._stop = False
        self._reload_requested = False
        self._install_sighup()

    def _install_sighup(self):
        import signal
        if not hasattr(signal, 'SIGHUP'):
            return
        try:
            def _on_hup(signum, frame):
                self._reload_requested = True
                self.logger.info("[scheduler] SIGHUP — запрошена перезагрузка плагинов")

            signal.signal(signal.SIGHUP, _on_hup)
        except Exception:
            pass

    def stop(self):
        self._stop = True

    def run_task(self, task):
        """Выполняет одну задачу"""
        from lib.scheduler.cron import CronExpression

        self.logger.info(f"[scheduler] Запуск задачи '{task.name}' -> {task.command}")
        self.storage.mark_running(task.id)

        try:
            # Парсим команду и аргументы
            parts = [task.command]
            for k, v in (task.args or {}).items():
                if isinstance(v, bool):
                    if v:
                        parts.append(f'--{k}')
                else:
                    parts.append(f'--{k}={v}')

            parser = ArgumentParser()
            parser.parse(parts)

            commands = self.command_loader.load_commands()
            cmd_name = parser.command

            if cmd_name not in commands:
                raise RuntimeError(f"Команда '{cmd_name}' не найдена")

            ctx = {
                'config': self.config,
                'logger': self.logger,
                'args': parser.options,
                'root_dir': self.root_dir,
                'command_name': cmd_name,
            }

            result = commands[cmd_name]['execute'](ctx)

            if result and result != 0:
                self.storage.mark_done(task.id, 'error', f"exit code {result}")
                self.logger.error(f"[scheduler] Задача '{task.name}' завершилась с кодом {result}")
            else:
                self.storage.mark_done(task.id, 'ok', None)
                self.logger.info(f"[scheduler] Задача '{task.name}' выполнена успешно")

        except Exception as e:
            tb = traceback.format_exc()
            self.storage.mark_done(task.id, 'error', f"{e}\n{tb[:2000]}")
            self.logger.error(f"[scheduler] Ошибка в задаче '{task.name}': {e}", exc_info=True)

    def tick(self):
        """Проверяет задачи и запускает подходящие"""
        from lib.scheduler.cron import CronExpression

        now = datetime.now().replace(second=0, microsecond=0)
        tasks = self.storage.list()

        for task in tasks:
            if not task.enabled:
                continue
            try:
                cron = CronExpression(task.cron)
            except ValueError as e:
                self.logger.error(f"[scheduler] Плохое cron-выражение у '{task.name}': {e}")
                continue

            if cron.matches(now):
                # Защита от повторного запуска в ту же минуту
                if task.last_run and task.last_run.replace(second=0, microsecond=0) == now:
                    continue
                self.run_task(task)

    def run_loop(self, interval=30):
        """Бесконечный цикл: проверяет каждые interval секунд"""
        self.logger.info(f"[scheduler] Старт цикла (интервал {interval}с)")
        print(f"⏱  Планировщик запущен. Интервал проверки: {interval}с")
        print("   Для остановки — Ctrl+C")

        try:
            while not self._stop:
                try:
                    while not self._stop.is_set():
                        if self._reload_requested:
                            self._reload_requested = False
                            self._do_reload_plugins()
                    self.tick()
                except Exception as e:
                    self.logger.error(f"[scheduler] Ошибка в tick: {e}", exc_info=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            print()
            self.logger.info("[scheduler] Остановлен пользователем")

    def _do_reload_plugins(self):
        try:
            from lib.plugins import get_manager
            from lib.plugins.reload import PluginReloader
            mgr = get_manager()
            reloader = PluginReloader(
                mgr, root_dir=self.root_dir,
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
                    self.logger.info(f"[scheduler] Плагин '{name}' перезагружен")
                else:
                    self.logger.error(f"[scheduler] Ошибка reload '{name}'")
        except Exception as e:
            self.logger.error(f"[scheduler] reload плагинов: {e}",
                              exc_info=True)
