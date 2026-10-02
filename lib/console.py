"""
Красивый вывод в консоль: цвета, таблицы, прогресс-бары, баннеры.
"""
import os
import shutil
import signal
import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional


# ══════════════════════════════════════════════════════════════════════
#                        ОБЩИЕ УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════════

def _is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _term_width(default: int = 80) -> int:
    try:
        return os.get_terminal_size(sys.stdout.fileno()).columns
    except Exception:
        try:
            return os.get_terminal_size().columns
        except Exception:
            return default


def _fmt_seconds(s: float) -> str:
    if s < 0:
        s = 0
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int((s % 3600) // 60):02d}m"


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r'\033\[[0-9;]*[A-Za-z]', '', s)


class _SizeWatcher:
    """
    Следит за SIGWINCH (изменение размера терминала) и вызывает callback.

    На Windows SIGWINCH отсутствует — там возвращаем noop.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._callbacks: list[Callable[[int, int], None]] = []
        self._installed = False
        self._old_handler = None

    @classmethod
    def instance(cls) -> '_SizeWatcher':
        with cls._lock:
            if cls._instance is None:
                cls._instance = _SizeWatcher()
            return cls._instance

    def add(self, cb: Callable[[int, int], None]):
        self._callbacks.append(cb)
        self._install()

    def remove(self, cb: Callable[[int, int], None]):
        if cb in self._callbacks:
            self._callbacks.remove(cb)
        if not self._callbacks:
            self._uninstall()

    def _install(self):
        if self._installed:
            return
        if not hasattr(signal, 'SIGWINCH'):
            return  # Windows
        try:
            self._old_handler = signal.getsignal(signal.SIGWINCH)

            def _handler(signum, frame):
                w, h = _term_width(), 0
                try:
                    h = os.get_terminal_size(sys.stdout.fileno()).lines
                except Exception:
                    pass
                for cb in list(self._callbacks):
                    try:
                        cb(w, h)
                    except Exception:
                        pass

            signal.signal(signal.SIGWINCH, _handler)
            self._installed = True
        except Exception:
            pass

    def _uninstall(self):
        if not self._installed:
            return
        try:
            if self._old_handler is not None:
                signal.signal(signal.SIGWINCH, self._old_handler)
        except Exception:
            pass
        self._installed = False

# ══════════════════════════════════════════════════════════════════════
#                    STICKY PROGRESS (прилипающий бар)
# ══════════════════════════════════════════════════════════════════════

class _StdoutProxy:
    """
    Прокси sys.stdout / sys.stderr.

    Пока есть активный live-renderer, весь вывод идёт через
    console.write_above_live(), который стирает область и печатает над ней.
    """

    def __init__(self, original, console: 'Console'):
        self._original = original
        self._console = console
        for attr in ('encoding', 'errors', 'name', 'mode',
                     'fileno', 'buffer', 'newlines'):
            if hasattr(original, attr):
                try:
                    setattr(self, attr, getattr(original, attr))
                except Exception:
                    pass

    def write(self, data: str) -> int:
        live = self._console._live_renderer
        if live is not None and live.is_active and not live.is_writing:
            live.write_above(data)
            return len(data)
        return self._original.write(data)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return self._original.isatty()
        except Exception:
            return False



class Live:
    """
    Область из нескольких строк, которая живёт внизу терминала
    и перерисовывается.

    Все рендереры (StickyProgress, MultiProgress, TaskTree) построены на нём.

    Контракт наследника — реализовать `render_lines(width) -> list[str]`.
    """

    def __init__(self, console: 'Console',
                 transient: bool = True,
                 refresh_per_sec: float = 10.0):
        self.console = console
        self.transient = transient
        self.refresh_per_sec = max(1.0, refresh_per_sec)

        self._is_active = False
        self._is_writing = False
        self._lock = threading.RLock()
        self._last_drawn_at = 0.0
        self._rendered_lines = 0
        self._tty = _is_tty() and console.use_color
        self._width = _term_width()
        self._size_watcher = _SizeWatcher.instance()
        self._on_resize_cb = self._on_resize

    # ─────────── Публичное ───────────

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def is_writing(self) -> bool:
        return self._is_writing

    def start(self):
        if self._is_active:
            return self
        self._is_active = True
        self.console._live_renderer = self
        self.console._install_proxy()
        if self._tty:
            sys.stdout.write('\033[?25l')   # скрыть курсор
            sys.stdout.flush()
        self._size_watcher.add(self._on_resize_cb)
        self._redraw(force=True)
        return self

    def close(self):
        with self._lock:
            if not self._is_active:
                return
            self._is_active = False

            self._size_watcher.remove(self._on_resize_cb)

            if self._tty:
                self._is_writing = True
                try:
                    if self.transient:
                        self._erase_lines(self._rendered_lines)
                        self._rendered_lines = 0
                    else:
                        # Оставляем финальный кадр как есть
                        pass
                    sys.stdout.write('\033[?25h')   # показать курсор
                    sys.stdout.flush()
                finally:
                    self._is_writing = False
            else:
                if not self.transient:
                    for line in self.render_lines(self._width):
                        print(line)

            if self.console._live_renderer is self:
                self.console._live_renderer = None
            self.console._uninstall_proxy_if_idle()

    def refresh(self, force: bool = False):
        with self._lock:
            if not self._is_active:
                return
            now = time.monotonic()
            if not force and now - self._last_drawn_at < 1.0 / self.refresh_per_sec:
                return
            self._redraw(force=force)

    def write_above(self, data: str):
        """
        Печатает `data` над областью live. Перерисовывает область под ней.
        """
        if not self._is_active:
            sys.__stdout__.write(data)
            return

        if not self._tty:
            sys.__stdout__.write(data)
            return

        with self._lock:
            self._is_writing = True
            try:
                # Стереть текущую область
                self._erase_lines(self._rendered_lines)
                # Печатаем данные; гарантируем перевод строки
                if not data.endswith('\n'):
                    data = data + '\n'
                sys.stdout.write(data)
                # Рисуем область заново
                self._draw_lines(self.render_lines(self._width))
                sys.stdout.flush()
            finally:
                self._is_writing = False

    # ─────────── Переопределяемое ───────────

    def render_lines(self, width: int) -> list[str]:
        """Вернуть список строк для отрисовки. Реализуется наследником."""
        raise NotImplementedError

    # ─────────── Внутреннее ───────────

    def _on_resize(self, width: int, height: int):
        with self._lock:
            self._width = width
            if self._is_active:
                self._redraw(force=True)

    def _redraw(self, force: bool = False):
        if not self._is_active:
            return
        self._is_writing = True
        try:
            # Стираем старое
            self._erase_lines(self._rendered_lines)
            # Рендерим новое
            lines = self.render_lines(self._width)
            self._draw_lines(lines)
            sys.stdout.flush()
            self._rendered_lines = len(lines)
            self._last_drawn_at = time.monotonic()
        finally:
            self._is_writing = False

    def _draw_lines(self, lines: list[str]):
        if not lines:
            return
        for i, line in enumerate(lines):
            # Обрезаем по ширине с учётом ANSI
            line = _truncate_ansi(line, self._width)
            sys.stdout.write('\033[K')     # стереть строку
            sys.stdout.write(line)
            if i < len(lines) - 1:
                sys.stdout.write('\n')

    def _erase_lines(self, n: int):
        if n <= 0:
            return
        # Курсор стоит в конце последней строки области.
        # Поднимаемся на n-1 строк вверх, стираем каждую.
        if n > 1:
            sys.stdout.write(f'\033[{n - 1}A')
        for i in range(n):
            sys.stdout.write('\r\033[K')
            if i < n - 1:
                sys.stdout.write('\033[1B')
        if n > 1:
            sys.stdout.write(f'\033[{n - 1}A')


class StickyProgress(Live):
    """
    Прогресс-бар, прилипающий к низу терминала.

    Пример:
        with console.progress_ctx(total=100, prefix='Обработка') as bar:
            for i in range(100):
                do_work(i)
                bar.update(1)
                if i == 50:
                    print("обработана половина")   # появится над баром

    Бар:
        - рисуется на последней строке;
        - всё, что печатается через print()/logger — появляется выше;
        - по завершении бар стирается.

    Если терминал — не TTY (перенаправление в файл, pipe), бар
    автоматически отключается, и вывод идёт обычным потоком.
    """

    def __init__(self, console, total, prefix='', suffix='',
                 width=40, color=None, empty_color=None,
                 show_percent=True, show_counter=True, show_eta=False,
                 transient=True, refresh_per_sec=10.0,
                 bar_char='█', empty_char='░',
                 left_bracket='|', right_bracket='|'):
        super().__init__(console, transient=transient,
                         refresh_per_sec=refresh_per_sec)
        self.total = max(0, int(total))
        self.prefix = prefix
        self.suffix = suffix
        self.bar_width = width
        self.color = color or Color.BRIGHT_GREEN
        self.empty_color = empty_color or Color.BRIGHT_BLACK
        self.show_percent = show_percent
        self.show_counter = show_counter
        self.show_eta = show_eta
        self.bar_char = bar_char
        self.empty_char = empty_char
        self.left_bracket = left_bracket
        self.right_bracket = right_bracket

        self.current = 0
        self._started_at = time.monotonic()

    # ─── API ───

    def update(self, n: int = 1):
        with self._lock:
            self.current = min(self.total, self.current + n)
            self.refresh()
            if self.current >= self.total:
                self.close()

    def set(self, value: int):
        with self._lock:
            self.current = max(0, min(self.total, value))
            self.refresh(force=True)
            if self.current >= self.total:
                self.close()

    def set_description(self, prefix: str = None, suffix: str = None):
        with self._lock:
            if prefix is not None:
                self.prefix = prefix
            if suffix is not None:
                self.suffix = suffix
            self.refresh(force=True)

    # ─── Render ───

    def render_lines(self, width: int) -> list[str]:
        if self.total > 0:
            percent = min(1.0, self.current / self.total)
        else:
            percent = 1.0

        filled = int(self.bar_width * percent)
        empty = self.bar_width - filled

        if self.console.use_color:
            bar = (
                self.console._c(self.color, self.bar_char * filled)
                + self.console._c(self.empty_color, self.empty_char * empty)
            )
        else:
            bar = self.bar_char * filled + self.empty_char * empty

        parts = []
        if self.prefix:
            parts.append(self.prefix)
        parts.append(f"{self.left_bracket}{bar}{self.right_bracket}")
        if self.show_percent:
            parts.append(f"{percent * 100:5.1f}%")
        if self.show_counter:
            parts.append(f"{self.current}/{self.total}")
        if self.show_eta and self._started_at is not None and self.current > 0:
            elapsed = time.monotonic() - self._started_at
            if self.current < self.total:
                eta = elapsed * (self.total - self.current) / self.current
                parts.append(f"ETA {_fmt_seconds(eta)}")
            else:
                parts.append(f"за {_fmt_seconds(elapsed)}")
        if self.suffix:
            parts.append(self.suffix)

        return [' '.join(parts)]

class MultiProgress(Live):
    """
    Несколько прогресс-баров одновременно, каждый на своей строке.

    Пример:
        with console.multi_progress() as mp:
            b1 = mp.add(100, prefix='Скачивание')
            b2 = mp.add(50,  prefix='Распаковка')
            for i in range(100):
                b1.update()
                if i % 2 == 0:
                    b2.update()
    """

    def __init__(self, console, transient=True, refresh_per_sec=10.0):
        super().__init__(console, transient=transient,
                         refresh_per_sec=refresh_per_sec)
        self._bars: list[dict] = []

    def add(self, total: int, prefix: str = '', suffix: str = '',
            width: int = 30, color: str = None, empty_color: str = None,
            show_percent: bool = True, show_counter: bool = True,
            show_eta: bool = False,
            bar_char: str = '█', empty_char: str = '░') -> 'MultiBarHandle':
        bar_id = len(self._bars)
        self._bars.append({
            'id': bar_id,
            'total': max(0, int(total)),
            'current': 0,
            'prefix': prefix,
            'suffix': suffix,
            'width': width,
            'color': color or Color.BRIGHT_GREEN,
            'empty_color': empty_color or Color.BRIGHT_BLACK,
            'show_percent': show_percent,
            'show_counter': show_counter,
            'show_eta': show_eta,
            'bar_char': bar_char,
            'empty_char': empty_char,
            'started_at': time.monotonic(),
            'done': False,
        })
        self.refresh(force=True)
        return MultiBarHandle(self, bar_id)

    # ─── Внутреннее ───

    def _update_bar(self, bar_id: int, delta: int = None, value: int = None):
        with self._lock:
            bar = self._bars[bar_id]
            if value is not None:
                bar['current'] = max(0, min(bar['total'], value))
            elif delta is not None:
                bar['current'] = min(bar['total'], bar['current'] + delta)

            if bar['current'] >= bar['total'] and not bar['done']:
                bar['done'] = True

            self.refresh()

    def _set_bar_description(self, bar_id: int, prefix=None, suffix=None):
        with self._lock:
            bar = self._bars[bar_id]
            if prefix is not None:
                bar['prefix'] = prefix
            if suffix is not None:
                bar['suffix'] = suffix
            self.refresh(force=True)

    def _remove_bar(self, bar_id: int):
        with self._lock:
            self._bars = [b for b in self._bars if b['id'] != bar_id]
            self.refresh(force=True)

    def render_lines(self, width: int) -> list[str]:
        lines = []
        for bar in self._bars:
            lines.append(self._render_bar(bar, width))
        return lines

    def _render_bar(self, bar: dict, width: int) -> str:
        total = bar['total']
        current = bar['current']
        percent = min(1.0, current / total) if total > 0 else 1.0

        bw = bar['width']
        filled = int(bw * percent)
        empty = bw - filled

        if self.console.use_color:
            body = (
                self.console._c(bar['color'], bar['bar_char'] * filled)
                + self.console._c(bar['empty_color'], bar['empty_char'] * empty)
            )
        else:
            body = bar['bar_char'] * filled + bar['empty_char'] * empty

        parts = []
        if bar['prefix']:
            parts.append(bar['prefix'])
        parts.append(f"|{body}|")
        if bar['show_percent']:
            parts.append(f"{percent*100:5.1f}%")
        if bar['show_counter']:
            parts.append(f"{current}/{total}")
        if bar['show_eta'] and current > 0:
            elapsed = time.monotonic() - bar['started_at']
            if current < total:
                eta = elapsed * (total - current) / current
                parts.append(f"ETA {_fmt_seconds(eta)}")
        if bar['suffix']:
            parts.append(bar['suffix'])

        return ' '.join(parts)


class MultiBarHandle:
    """Ручка одной полосы внутри MultiProgress."""

    def __init__(self, mp: MultiProgress, bar_id: int):
        self._mp = mp
        self._id = bar_id
        self._closed = False

    def update(self, n: int = 1):
        if self._closed:
            return
        self._mp._update_bar(self._id, delta=n)

    def set(self, value: int):
        if self._closed:
            return
        self._mp._update_bar(self._id, value=value)

    def set_description(self, prefix: str = None, suffix: str = None):
        if self._closed:
            return
        self._mp._set_bar_description(self._id, prefix=prefix, suffix=suffix)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._mp._remove_bar(self._id)

class Spinner(Live):
    """
    Анимация из символов для задач без известного total.

    Пример:
        with console.spinner('Установка зависимостей') as sp:
            run_long_task()
            sp.set_description('Сборка')
            run_another()
    """

    FRAMES = {
        'braille': ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
        'line':    ['|', '/', '-', '\\'],
        'dots':    ['⠁', '⠂', '⠄', '⡀', '⢀', '⠠', '⠐', '⠈'],
        'arrows':  ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙'],
        'clock':   ['🕐', '🕑', '🕒', '🕓', '🕔', '🕕',
                    '🕖', '🕗', '🕘', '🕙', '🕚', '🕛'],
    }

    def __init__(self, console, text='', *, frames='braille',
                 interval=0.08, color=None, transient=True,
                 show_elapsed=True):
        super().__init__(console, transient=transient,
                         refresh_per_sec=30.0)
        self.text = text
        self.frames = self.FRAMES.get(frames, self.FRAMES['braille'])
        self.interval = interval
        self.color = color or Color.BRIGHT_CYAN
        self.show_elapsed = show_elapsed

        self._started_at = time.monotonic()
        self._frame_idx = 0
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    def start(self):
        super().start()
        self._start_animation()
        return self

    def close(self):
        self._stop_evt.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=1.0)
        super().close()

    def set_description(self, text: str):
        with self._lock:
            self.text = text
            self.refresh(force=True)

    def render_lines(self, width: int) -> list[str]:
        frame = self.frames[self._frame_idx % len(self.frames)]
        if self.console.use_color:
            frame = self.console._c(self.color, frame)
        parts = [f"{frame} {self.text}"]
        if self.show_elapsed:
            elapsed = time.monotonic() - self._started_at
            parts.append(f"[{_fmt_seconds(elapsed)}]")
        return [' '.join(parts)]

    # ─── Внутреннее ───

    def _start_animation(self):
        def loop():
            while not self._stop_evt.wait(self.interval):
                with self._lock:
                    self._frame_idx += 1
                self.refresh()
        self._timer_thread = threading.Thread(
            target=loop, daemon=True, name='homer-spinner',
        )
        self._timer_thread.start()

def _truncate_ansi(s: str, width: int) -> str:
    """
    Обрезает строку до `width` видимых символов, сохраняя ANSI-последовательности.
    """
    if _strip_ansi(s) and len(_strip_ansi(s)) <= width:
        return s

    out = []
    visible = 0
    i = 0
    while i < len(s) and visible < width:
        if s[i] == '\033' and i + 1 < len(s) and s[i + 1] == '[':
            j = i + 2
            while j < len(s) and not s[j].isalpha():
                j += 1
            if j < len(s):
                out.append(s[i:j + 1])
                i = j + 1
                continue
        out.append(s[i])
        visible += 1
        i += 1
    # Закрываем возможные ANSI
    return ''.join(out) + ('\033[0m' if '\033[' in ''.join(out) else '')


class Color:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'

    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'


class TaskTree(Live):
    """
    Дерево задач с прогрессом.

    Использование:
        with console.task_tree('Сборка релиза') as tree:
            with tree.task('Скачивание зависимостей', total=10) as t:
                for i in range(10):
                    time.sleep(0.1)
                    t.update()

            with tree.task('Компиляция', total=5) as t:
                for i in range(5):
                    time.sleep(0.2)
                    t.update()

            tree.task_done('Тесты пропущены (кеш)', status='skipped')
    """

    STATUS_ICONS = {
        'pending': '·',
        'running': '⠹',
        'done':    '✔',
        'failed':  '✖',
        'skipped': '⤼',
        'warning': '⚠',
    }

    STATUS_COLORS = {
        'pending': Color.BRIGHT_BLACK,
        'running': Color.BRIGHT_CYAN,
        'done':    Color.BRIGHT_GREEN,
        'failed':  Color.BRIGHT_RED,
        'skipped': Color.BRIGHT_BLACK,
        'warning': Color.BRIGHT_YELLOW,
    }

    def __init__(self, console, root_text: str = '',
                 transient=True, refresh_per_sec=20.0,
                 indent: str = '  '):
        super().__init__(console, transient=transient,
                         refresh_per_sec=refresh_per_sec)
        self.root_text = root_text
        self.indent = indent
        self._nodes: list[dict] = []      # плоский список, порядок = порядок вывода
        self._next_id = 0
        self._stop_evt = threading.Event()
        self._anim_thread: Optional[threading.Thread] = None
        self._started_at = time.monotonic()

    # ─── API ───

    def task(self, text: str, total: int = 0, *, parent: Optional[int] = None,
             show_eta: bool = True, width: int = 24) -> 'TaskHandle':
        """
        Добавляет задачу. Возвращает хендл.
        Если parent=None — задача верхнего уровня (parent=root).
        """
        return self._add_node(text, total=total, parent=parent,
                              show_eta=show_eta, width=width)

    def task_done(self, text: str, status: str = 'done',
                  error: Optional[str] = None) -> 'TaskHandle':
        """
        Добавляет сразу завершённую задачу (без прогресса).
        """
        h = self._add_node(text, total=0, parent=None)
        with self._lock:
            self._nodes[h._id]['status'] = status
            if error:
                self._nodes[h._id]['error'] = error
        h.close(silent=True)
        return h

    # ─── Хендл задачи ───

    def _add_node(self, text: str, total: int = 0,
                  parent: Optional[int] = None,
                  show_eta: bool = True, width: int = 24) -> 'TaskHandle':
        node = {
            'id': self._next_id,
            'text': text,
            'total': max(0, int(total)),
            'current': 0,
            'status': 'running' if total == 0 else 'running',
            'parent': parent,
            'show_eta': show_eta,
            'width': width,
            'started_at': time.monotonic(),
            'error': None,
            'children': [],
        }
        self._next_id += 1
        with self._lock:
            self._nodes.append(node)
            if parent is not None:
                self._nodes[parent]['children'].append(node['id'])
        self.refresh(force=True)
        return TaskHandle(self, node['id'])

    def _update_task(self, node_id: int, delta: int = None, value: int = None):
        with self._lock:
            node = self._nodes[node_id]
            if value is not None:
                node['current'] = max(0, min(node['total'], value))
            elif delta is not None:
                node['current'] = min(node['total'], node['current'] + delta)
            if node['total'] > 0 and node['current'] >= node['total']:
                node['status'] = 'done'
        self.refresh()

    def _finish_task(self, node_id: int, status: str = 'done',
                     error: str = None):
        with self._lock:
            node = self._nodes[node_id]
            node['status'] = status
            if error:
                node['error'] = error
            if status == 'done' and node['total'] > 0:
                node['current'] = node['total']
        self.refresh(force=True)

    def _set_text(self, node_id: int, text: str):
        with self._lock:
            self._nodes[node_id]['text'] = text
        self.refresh(force=True)

    # ─── Render ───

    def render_lines(self, width: int) -> list[str]:
        lines = []
        if self.root_text:
            elapsed = time.monotonic() - self._started_at
            lines.append(f"{self.root_text} [{_fmt_seconds(elapsed)}]")
        for node in self._nodes:
            lines.append(self._render_node(node))
        return lines

    def _render_node(self, node: dict) -> str:
        depth = self._depth(node['id'])
        indent = self.indent * depth

        status = node['status']
        icon = self.STATUS_ICONS.get(status, '·')
        icon_color = self.STATUS_COLORS.get(status, Color.WHITE)

        if self.console.use_color:
            icon_str = self.console._c(icon_color, icon)
        else:
            icon_str = icon

        parts = [f"{indent}{icon_str} {node['text']}"]

        # Прогресс, если есть total
        if node['total'] > 0:
            percent = min(1.0, node['current'] / node['total'])
            bw = node['width']
            filled = int(bw * percent)
            empty = bw - filled
            if self.console.use_color:
                body = (
                    self.console._c(Color.BRIGHT_GREEN, '█' * filled)
                    + self.console._c(Color.BRIGHT_BLACK, '░' * empty)
                )
            else:
                body = '█' * filled + '░' * empty
            parts.append(f"|{body}| {node['current']}/{node['total']}")

            if node['show_eta'] and node['current'] > 0 and status == 'running':
                elapsed = time.monotonic() - node['started_at']
                if node['current'] < node['total']:
                    eta = elapsed * (node['total'] - node['current']) / node['current']
                    parts.append(f"ETA {_fmt_seconds(eta)}")

        # Ошибка/примечание
        if node['error']:
            parts.append(self.console._c(Color.BRIGHT_RED, node['error']))

        return ' '.join(parts)

    def _depth(self, node_id: int) -> int:
        depth = 0
        cur = self._nodes[node_id]
        while cur['parent'] is not None:
            depth += 1
            cur = self._nodes[cur['parent']]
        return depth

    # ─── Анимация running ───

    def start(self):
        super().start()
        self._start_anim()
        return self

    def close(self):
        self._stop_evt.set()
        if self._anim_thread is not None:
            self._anim_thread.join(timeout=1.0)
        super().close()

    def _start_anim(self):
        frames = Spinner.FRAMES['braille']

        def loop():
            idx = 0
            while not self._stop_evt.wait(0.1):
                idx += 1
                if any(n['status'] == 'running' for n in self._nodes):
                    with self._lock:
                        self.STATUS_ICONS['running'] = frames[idx % len(frames)]
                    self.refresh()

        self._anim_thread = threading.Thread(
            target=loop, daemon=True, name='homer-tasktree-anim',
        )
        self._anim_thread.start()


class TaskHandle:
    """Хендл одной задачи в дереве."""

    def __init__(self, tree: TaskTree, node_id: int):
        self._tree = tree
        self._id = node_id
        self._closed = False

    def update(self, n: int = 1):
        if self._closed:
            return
        self._tree._update_task(self._id, delta=n)

    def set(self, value: int):
        if self._closed:
            return
        self._tree._update_task(self._id, value=value)

    def set_text(self, text: str):
        if self._closed:
            return
        self._tree._set_text(self._id, text)

    def fail(self, error: str = None):
        self._tree._finish_task(self._id, status='failed', error=error)
        self._closed = True

    def warn(self, note: str = None):
        self._tree._finish_task(self._id, status='warning', error=note)
        self._closed = True

    def skip(self, note: str = None):
        self._tree._finish_task(self._id, status='skipped', error=note)
        self._closed = True

    def close(self, silent: bool = False):
        if self._closed:
            return
        self._closed = True
        if not silent:
            self._tree._finish_task(self._id, status='done')

    # Контекстный менеджер
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.close()
        else:
            self.fail(str(exc_val))

class Console:
    def __init__(self, force_color=None):
        if force_color is None:
            self.use_color = (
                sys.stdout.isatty()
                and os.environ.get('NO_COLOR') is None
                and os.environ.get('TERM') != 'dumb'
            )
        else:
            self.use_color = force_color
        self._active_bar: Optional[StickyProgress] = None
        self._orig_stdout = None
        self._orig_stderr = None
        self._proxy_installed = False
        self._live_renderer: Optional[Live] = None
        self._orig_stdout = None
        self._orig_stderr = None
        self._proxy_installed = False

        # Старое имя оставлено для совместимости
        @property
        def _active_bar(self):
            return self._live_renderer

        @_active_bar.setter
        def _active_bar(self, value):
            self._live_renderer = value

        def _install_proxy(self):
            if self._proxy_installed:
                return
            self._orig_stdout = sys.stdout
            self._orig_stderr = sys.stderr
            sys.stdout = _StdoutProxy(self._orig_stdout, self)
            sys.stderr = _StdoutProxy(self._orig_stderr, self)
            self._proxy_installed = True

        def _uninstall_proxy_if_idle(self):
            if not self._proxy_installed:
                return
            if self._live_renderer is not None:
                return
            sys.stdout = self._orig_stdout or sys.__stdout__
            sys.stderr = self._orig_stderr or sys.__stderr__
            self._proxy_installed = False

    def _c(self, color, text):
        if not self.use_color:
            return text
        return f"{color}{text}{Color.RESET}"

    @property
    def width(self):
        return shutil.get_terminal_size((80, 24)).columns

    def print(self, text='', **kwargs):
        print(text, **kwargs)

    def line(self, char='─', color=Color.BRIGHT_BLACK, width=None):
        w = width or self.width
        print(self._c(color, char * w))

    def newline(self):
        print()

    def success(self, msg):
        print(f"{self._c(Color.BRIGHT_GREEN, '✔')} {msg}")

    def error(self, msg):
        print(f"{self._c(Color.BRIGHT_RED, '✖')} {msg}")

    def warning(self, msg):
        print(f"{self._c(Color.BRIGHT_YELLOW, '⚠')} {msg}")

    def info(self, msg):
        print(f"{self._c(Color.BRIGHT_BLUE, 'ℹ')} {msg}")

    def debug(self, msg):
        print(f"{self._c(Color.BRIGHT_BLACK, '·')} {self._c(Color.DIM, msg)}")

    def comment(self, msg):
        print(self._c(Color.BRIGHT_BLACK, msg))

    def title(self, text):
        print(self._c(Color.BOLD + Color.BRIGHT_CYAN, text))
        print(self._c(Color.BRIGHT_BLACK, '─' * len(text)))

    def colored(self, text, color):
        return self._c(color, text)

    def bold(self, text):
        return self._c(Color.BOLD, text)

    def dim(self, text):
        return self._c(Color.DIM, text)

    def banner(self, title, subtitle='', color=Color.BRIGHT_CYAN):
        w = self.width
        print()
        print(self._c(color, '═' * w))
        print(self._c(Color.BOLD + color, f"  {title}"))
        if subtitle:
            print(self._c(Color.DIM, f"  {subtitle}"))
        print(self._c(color, '═' * w))
        print()

    def table(self, headers, rows, borders=True,
              header_color=Color.BRIGHT_CYAN, align=None, padding=1):
        if not headers:
            return

        rows = [[('' if c is None else str(c)) for c in row] for row in rows]
        ncols = len(headers)

        widths = [len(str(h)) for h in headers]
        for row in rows:
            for i in range(min(ncols, len(row))):
                for line in str(row[i]).split('\n'):
                    widths[i] = max(widths[i], len(line))

        if align is None:
            align = ['l'] * ncols
        pad = ' ' * padding

        def fmt_cell(text, width, align):
            text = str(text)
            if align == 'r':
                return pad + text.rjust(width) + pad
            if align == 'c':
                return pad + text.center(width) + pad
            return pad + text.ljust(width) + pad

        def build_sep(left, mid, right, char='─'):
            parts = [char * (w + padding * 2) for w in widths]
            return self._c(Color.BRIGHT_BLACK, left + mid.join(parts) + right)

        if borders:
            print(build_sep('┌', '┬', '┐'))

        header_cells = [
            self._c(Color.BOLD + header_color,
                    fmt_cell(h, widths[i], align[i]))
            for i, h in enumerate(headers)
        ]
        if borders:
            sep = self._c(Color.BRIGHT_BLACK, '│')
            print(f"{sep}{sep.join(header_cells)}{sep}")
            print(build_sep('├', '┼', '┤'))
        else:
            print('  '.join(header_cells))

        for row in rows:
            cells = []
            for i in range(ncols):
                value = row[i] if i < len(row) else ''
                lines = str(value).split('\n')
                cells.append([
                    fmt_cell(line, widths[i], align[i]) for line in lines
                ])
            max_lines = max(len(c) for c in cells)
            for line_idx in range(max_lines):
                rendered = []
                for i, cell_lines in enumerate(cells):
                    txt = (cell_lines[line_idx]
                           if line_idx < len(cell_lines)
                           else ' ' * (widths[i] + padding * 2))
                    rendered.append(txt)
                if borders:
                    sep = self._c(Color.BRIGHT_BLACK, '│')
                    print(f"{sep}{sep.join(rendered)}{sep}")
                else:
                    print('  '.join(rendered))

        if borders:
            print(build_sep('└', '┴', '┘'))

    def progress(self, current, total, prefix='', suffix='', width=40,
                 color=Color.BRIGHT_GREEN, clear=True, sticky=None,
                 show_eta=False, refresh_per_sec=10.0):
        """
        Прогресс-бар.

        current, total     — позиция
        prefix, suffix     — текст до/после бара
        width              — ширина полосы
        color              — цвет заливки
        clear              — убрать бар после 100%
        sticky             — True: bar «прилипает» к низу; None: авто
                             (sticky=True если TTY, иначе False)
        show_eta           — показывать оценку оставшегося времени
        refresh_per_sec    — ограничение частоты отрисовки
        """
        if sticky is None:
            sticky = sys.stdout.isatty()

        if sticky:
            # Ленивая инициализация sticky-бара
            bar = self._active_bar
            if bar is None or bar.total != total or bar.prefix != prefix:
                # Если старый бар есть — закрыть
                if bar is not None:
                    bar.close()
                    self._active_bar = None

                bar = StickyProgress(
                    self, total=total, prefix=prefix, suffix=suffix,
                    width=width, color=color,
                    show_eta=show_eta,
                    refresh_per_sec=refresh_per_sec,
                )
                self._install_proxy()
                self._active_bar = bar
                bar.start()

            bar.set(current)

            if current >= total and clear:
                bar.close()
                self._active_bar = None
                self._uninstall_proxy_if_idle()
            return

        # ─── Fallback: старый режим с \r ───
        if total <= 0:
            return
        percent = current / total
        filled = int(width * percent)
        if self.use_color:
            bar = (f"{color}{'█' * filled}"
                   f"{Color.BRIGHT_BLACK}{'░' * (width - filled)}{Color.RESET}")
        else:
            bar = '█' * filled + '░' * (width - filled)
        line = f"\r{prefix} |{bar}| {current}/{total} ({percent * 100:5.1f}%) {suffix}"
        print(line, end='', flush=True)
        if current >= total and clear:
            print()

    @contextmanager
    def multi_progress(self, transient=True, refresh_per_sec=10.0):
        """
        Контекстный менеджер для нескольких баров.

        with console.multi_progress() as mp:
            b1 = mp.add(100, prefix='Скачивание')
            b2 = mp.add(50,  prefix='Распаковка')
            ...
        """
        mp = MultiProgress(self, transient=transient,
                           refresh_per_sec=refresh_per_sec)
        mp.start()
        try:
            yield mp
        finally:
            mp.close()

    @contextmanager
    def spinner(self, text='', **kwargs):
        """
        Контекстный менеджер спиннера.

        with console.spinner('Установка...') as sp:
            long_task()
            sp.set_description('Сборка')
        """
        sp = Spinner(self, text=text, **kwargs)
        sp.start()
        try:
            yield sp
        finally:
            sp.close()

    # ─────────── Прилипающий прогресс ───────────

    @contextmanager
    def progress_ctx(self, total: int, prefix: str = '',
                     suffix: str = '', **kwargs):
        """
        Контекстный менеджер прогресс-бара, прилипающего к низу.

        Пример:
            with console.progress_ctx(100, prefix='Обработка') as bar:
                for i in range(100):
                    ...
                    bar.update()
                    if i == 50:
                        print("Половина готова")
        """
        bar = StickyProgress(self, total=total, prefix=prefix,
                             suffix=suffix, **kwargs)
        self._install_proxy()
        self._active_bar = bar
        bar.start()
        try:
            yield bar
        finally:
            bar.close()
            self._active_bar = None
            self._uninstall_proxy_if_idle()

    @contextmanager
    def task_tree(self, root_text: str = '', **kwargs):
        """
        with console.task_tree('Сборка релиза') as tree:
            with tree.task('Шаг 1', total=10) as t:
                ...
        """
        tree = TaskTree(self, root_text=root_text, **kwargs)
        tree.start()
        try:
            yield tree
        finally:
            tree.close()

    # ─────────── Внутреннее ───────────

    def _install_proxy(self):
        if self._proxy_installed:
            return
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _StdoutProxy(self._orig_stdout, self)
        sys.stderr = _StdoutProxy(self._orig_stderr, self)
        self._proxy_installed = True

    def _uninstall_proxy_if_idle(self):
        if not self._proxy_installed:
            return
        if self._active_bar is not None:
            return
        sys.stdout = self._orig_stdout or sys.__stdout__
        sys.stderr = self._orig_stderr or sys.__stderr__
        self._proxy_installed = False

    def list_item(self, key, value=None, indent=2, key_color=Color.BRIGHT_YELLOW):
        prefix = ' ' * indent + self._c(Color.BRIGHT_BLACK, '• ')
        if value is not None:
            print(f"{prefix}{self._c(key_color, str(key))}: {value}")
        else:
            print(f"{prefix}{key}")

    def key_value(self, key, value, key_width=20, indent=2):
        key_str = self._c(Color.BRIGHT_YELLOW, str(key).ljust(key_width))
        print(f"{' ' * indent}{key_str} {value}")

    def panel(self, content, title=None, color=Color.BRIGHT_CYAN):
        lines = content.split('\n') if isinstance(content, str) else content
        w = max(len(line) for line in lines) + 4
        if title:
            w = max(w, len(title) + 4)
        if title:
            top = (f"╭─ {self._c(Color.RESET, title)} {color}"
                   + '─' * (w - len(title) - 4) + '╮')
        else:
            top = '╭' + '─' * (w - 2) + '╮'
        print(self._c(color, top))
        for line in lines:
            padding = ' ' * (w - 3 - len(line))
            print(f"{self._c(color, '│')}  {line}{padding}{self._c(color, '│')}")
        print(self._c(color, '╰' + '─' * (w - 1) + '╯'))

    def section(self, title, color=Color.BRIGHT_MAGENTA):
        print()
        print(self._c(Color.BOLD + color, f"▸ {title}"))
        print(self._c(Color.BRIGHT_BLACK, '─' * self.width))
        print()

    def ask(self, question, default=None):
        prompt = f"{self._c(Color.BRIGHT_YELLOW, '?')} {question}"
        if default is not None:
            prompt += f" {self._c(Color.DIM, f'[{default}]')}"
        prompt += ': '
        value = input(prompt).strip()
        return value if value else default

    def confirm(self, question, default=False):
        suffix = 'Y/n' if default else 'y/N'
        answer = self.ask(f"{question} ({suffix})",
                          default='y' if default else 'n')
        return answer.lower() in ('y', 'yes', 'д', 'да')


console = Console()
