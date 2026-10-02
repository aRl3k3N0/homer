"""
Интерактивная сессия выполнения команды Homer.

Запускает команду в отдельном потоке, перехватывает:
    - sys.stdout / sys.stderr — поток вывода в браузер;
    - builtins.input — запросы к пользователю через браузер.

Протокол сообщений в WebSocket:
    Сервер → клиенту:
        {'type': 'output', 'stream': 'stdout'|'stderr', 'data': '...'}
        {'type': 'input_request', 'prompt': 'Как вас зовут? ', 'id': 'q1'}
        {'type': 'input_request', 'prompt': 'Продолжить? (Y/n) ', 'id': 'q2',
         'default': 'y'}
        {'type': 'done', 'exit_code': 0}
        {'type': 'error', 'message': '...'}
        {'type': 'started', 'command': 'cmdb:update', 'args': {...}}

    Клиент → серверу:
        {'type': 'input_response', 'id': 'q1', 'value': 'Иван'}
        {'type': 'signal', 'signal': 'SIGINT'}
        {'type': 'stdin_data', 'data': '...'}   # опционально, для shell-команд
"""

from __future__ import annotations

import builtins
import io
import queue
import sys
import threading
import traceback
from typing import Optional
import uuid


class _OutputStream(io.TextIOBase):
    """Поток, транслирующий вывод в очередь сообщений."""

    def __init__(self, session, stream_name: str):
        self.session = session
        self.stream_name = stream_name

    def write(self, data: str) -> int:
        if data:
            self.session._push_output(self.stream_name, data)
        return len(data)

    def flush(self):
        pass

    def isatty(self) -> bool:
        return False


class ConsoleSession:
    """
    Одна сессия выполнения команды.

    Использование:
        session = ConsoleSession(context, 'cmdb:update', {'user': 'cmdb'})
        session.start()          # запуск в фоне
        while True:
            msg = session.get_message(timeout=1)   # события
            ...
        session.send_input('q1', 'yes')            # ответ на input()
    """

    def __init__(
        self,
        context,
        command,
        args,
        history: HistoryStorage | None = None,
        user: str = 'anonymous',
        client_ip: str | None = None,
        user_agent: str | None = None,
        session_id: str | None = None,
    ):
        self.context = context
        self.command = command
        self.args = args
        self.history = history
        self.user = user
        self.client_ip = client_ip
        self.user_agent = user_agent
        self.session_id = session_id or str(uuid.uuid4())

        self._messages: queue.Queue[dict] = queue.Queue()
        self._input_waiters: dict[str, queue.Queue[str]] = {}
        self._input_counter = 0
        self._input_lock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._exit_code: Optional[int] = None

        self._history_id: str | None = None
        self._output_buffer: list[str] = []
        self._input_history: list[str] = []

    # ─────────── API ───────────

    def start(self):
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f'homer-console-{self.command}',
        )
        self._thread.start()

    def get_message(self, timeout: float = 1.0) -> Optional[dict]:
        try:
            return self._messages.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_input(self, request_id: str, value: str):
        waiter = self._input_waiters.get(request_id)
        if waiter is not None:
            waiter.put(value)

    def stop(self):
        self._stop_flag.set()
        # Разбудим всех ждущих ввода пустой строкой
        for waiter in list(self._input_waiters.values()):
            try:
                waiter.put_nowait('')
            except Exception:
                pass

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def exit_code(self) -> Optional[int]:
        return self._exit_code

    # ─────────── Внутреннее ───────────

    def _push_output(self, stream_name: str, data: str):
        if data:
            # Ограничиваем буфер
            if sum(len(x) for x in self._output_buffer) < 500_000:
                self._output_buffer.append(data)

        self._messages.put(
            {
                'type': 'output',
                'stream': stream_name,
                'data': data,
            }
        )

    def _next_input_id(self) -> str:
        with self._input_lock:
            self._input_counter += 1
            return f'q{self._input_counter}'

    def _fake_input(self, prompt: str = '') -> str:
        """Замена builtins.input() — запрашивает ввод через браузер."""
        if self._stop_flag.is_set():
            raise KeyboardInterrupt('session stopped')

        request_id = self._next_input_id()
        waiter: queue.Queue[str] = queue.Queue()
        self._input_waiters[request_id] = waiter

        self._messages.put(
            {
                'type': 'input_request',
                'id': request_id,
                'prompt': prompt or '',
            }
        )

        try:
            # Ждём ответа; но также позволяем остановить сессию
            while True:
                try:
                    value = waiter.get(timeout=0.5)  # внутри while
                    self._input_history.append(f"{prompt}→{value}")
                    return value
                except queue.Empty:
                    if self._stop_flag.is_set():
                        raise KeyboardInterrupt('session stopped')
        finally:
            self._input_waiters.pop(request_id, None)

    def _run(self):
        # Готовим контекст
        from lib.arguments import ArgumentParser
        from lib.command_loader import CommandLoader

        root_dir = self.context['root_dir']
        config = self.context['config']
        logger = self.context['logger']

        # Собираем argv для парсера
        parts = [self.command]
        for k, v in (self.args or {}).items():
            if isinstance(v, bool):
                if v:
                    parts.append(f'--{k}')
            else:
                parts.append(f'--{k}={v}')

        parser = ArgumentParser()
        parser.parse(parts)

        # Загружаем команды
        loader = CommandLoader(root_dir / 'commands')
        commands = loader.load_commands()
        try:
            from lib.commands import BUILTIN_COMMANDS

            for name, info in BUILTIN_COMMANDS.items():
                commands.setdefault(name, info)
        except Exception:
            pass

        cmd_name = parser.command
        if cmd_name not in commands:
            self._messages.put({'type': 'error', 'message': f"Команда '{cmd_name}' не найдена"})
            self._messages.put({'type': 'done', 'exit_code': 2})
            self._exit_code = 2
            return

        # Ленивая очередь
        from lib.queue import Dispatcher, QueueStorage

        _storage = None
        _dispatcher = None

        class _LazyQueue:
            def _get(self):
                nonlocal _storage, _dispatcher
                if _dispatcher is None:
                    _storage = QueueStorage(config)
                    _dispatcher = Dispatcher(
                        _storage,
                        config=config,
                        triggered_by=f'webui:{cmd_name}',
                    )
                return _dispatcher

            def __getattr__(self, name):
                return getattr(self._get(), name)

        ctx = {
            'config': config,
            'logger': logger,
            'args': parser.options,
            'root_dir': root_dir,
            'command_name': cmd_name,
            'commands': commands,
            'queue': _LazyQueue(),
        }

        # Создаём запись в истории
        if self.history is not None:
            try:
                self._history_id = self.history.start(
                    user=self.user,
                    command=cmd_name,
                    args=parser.options,
                    client_ip=self.client_ip,
                    user_agent=self.user_agent,
                    session_id=self.session_id,
                )
            except Exception as e:
                # Не роняем команду из-за истории
                self._messages.put({'type': 'error', 'message': f'history.start: {e}'})

        # Перехватываем stdout / stderr / input
        old_stdout, old_stderr, old_input = (
            sys.stdout,
            sys.stderr,
            builtins.input,
        )
        sys.stdout = _OutputStream(self, 'stdout')
        sys.stderr = _OutputStream(self, 'stderr')
        builtins.input = self._fake_input

        self._messages.put(
            {
                'type': 'started',
                'command': cmd_name,
                'args': parser.options,
            }
        )

        exit_code = 0
        try:
            result = commands[cmd_name]['execute'](ctx)
            if result is True or result is None:
                exit_code = 0
            elif result is False:
                exit_code = 1
            elif isinstance(result, int):
                exit_code = result
            else:
                exit_code = 0
        except KeyboardInterrupt:
            exit_code = 130
            self._messages.put(
                {'type': 'output', 'stream': 'stderr', 'data': '\n[прервано пользователем]\n'}
            )
        except SystemExit as e:
            exit_code = int(e.code) if isinstance(e.code, int) else 1
        except Exception as e:
            exit_code = 1
            tb = traceback.format_exc()
            self._messages.put({'type': 'output', 'stream': 'stderr', 'data': tb})
            self._messages.put({'type': 'error', 'message': str(e)})
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            builtins.input = old_input

            self._exit_code = exit_code

            # Сохраняем в историю
            if self.history is not None and self._history_id:
                try:
                    self.history.finish(
                        self._history_id,
                        exit_code=exit_code,
                        output=''.join(self._output_buffer),
                        input_log=self._input_history,
                    )
                except Exception as e:
                    self._messages.put({'type': 'error', 'message': f'history.finish: {e}'})

            self._messages.put(
                {'type': 'done', 'exit_code': exit_code, 'history_id': self._history_id}
            )
