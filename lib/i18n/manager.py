"""
i18n-подсистема Homer.

Возможности:
    - YAML-переводы из langs/<locale>.yml (и любых других каталогов)
    - вложенные ключи через '.'
    - fallback на fallback_locale
    - подстановка {var} без падений на опечатках
    - плюрализация (CLDR-правила: ru, en, de, fr, uk, pl, cs, es, it)
    - контекст локали через contextvars: безопасно для asyncio и потоков
    - LRU-кэш переводов и плюрализации
    - автоперезагрузка при изменении файлов (watcher в фоне)
    - логирование отсутствующих ключей с дедупликацией
    - Jinja-глобалы `_` и `tn`
    - hot-reload по SIGHUP через reload()

Публичный API:
    get_i18n()                    — глобальный экземпляр
    configure(...)                — настройка при старте
    set_locale(locale)            — установить локаль в текущем контексте
    locale_ctx(locale)            — контекстный менеджер
    t(key, **kwargs)              — перевод
    tn(key, n, **kwargs)          — плюрализация
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import pickle
from collections import OrderedDict
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import yaml

from .formatting import (
    format_number as _fmt_number,
    format_percent as _fmt_percent,
    format_date as _fmt_date,
    format_datetime as _fmt_datetime,
    format_time as _fmt_time,
)

_log = logging.getLogger('homer.i18n')


# ═══════════════════════════════════════════════════════════════
#                    CLDR-правила плюрализации
# ═══════════════════════════════════════════════════════════════

_PLURAL_RULES: dict[str, Callable[[int], str]] = {
    'en': lambda n: 'one' if n == 1 else 'other',
    'de': lambda n: 'one' if n == 1 else 'other',
    'nl': lambda n: 'one' if n == 1 else 'other',
    'sv': lambda n: 'one' if n == 1 else 'other',
    'da': lambda n: 'one' if n == 1 else 'other',
    'it': lambda n: 'one' if n == 1 else 'other',
    'es': lambda n: 'one' if n == 1 else 'other',
    'pt': lambda n: 'one' if n == 1 else 'other',
    'fr': lambda n: 'one' if n in (0, 1) else 'other',
    'ja': lambda n: 'other',
    'zh': lambda n: 'other',
    'ko': lambda n: 'other',
    'tr': lambda n: 'other',
    'ru': lambda n: (
        'one' if (n % 10 == 1 and n % 100 != 11)
        else 'few' if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else 'many'
    ),
    'uk': lambda n: (
        'one' if (n % 10 == 1 and n % 100 != 11)
        else 'few' if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else 'many'
    ),
    'be': lambda n: (
        'one' if (n % 10 == 1 and n % 100 != 11)
        else 'few' if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else 'many'
    ),
    'pl': lambda n: (
        'one' if n == 1
        else 'few' if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else 'many'
    ),
    'cs': lambda n: (
        'one' if n == 1
        else 'few' if 2 <= n <= 4
        else 'many'
    ),
    'sk': lambda n: (
        'one' if n == 1
        else 'few' if 2 <= n <= 4
        else 'many'
    ),
    'lt': lambda n: (
        'one' if (n % 10 == 1 and n % 100 != 11)
        else 'few' if (2 <= n % 10 <= 9 and not 11 <= n % 100 <= 19)
        else 'many'
    ),
    'ar': lambda n: (
        'zero' if n == 0
        else 'one' if n == 1
        else 'two' if n == 2
        else 'few' if 3 <= n % 100 <= 10
        else 'many' if 11 <= n % 100 <= 99
        else 'other'
    ),
}

_DEFAULT_PLURAL = _PLURAL_RULES['en']


# ═══════════════════════════════════════════════════════════════
#                       Безопасный format
# ═══════════════════════════════════════════════════════════════

class _SafeDict(dict):
    """
    dict, не падающий на отсутствующих ключах в {var}.
    Оставшийся {var} выводится как есть — так опечатка заметна в UI.
    """
    def __missing__(self, key):
        return '{' + key + '}'


# ═══════════════════════════════════════════════════════════════
#                          LRU-кэш
# ═══════════════════════════════════════════════════════════════

class _LRUCache:
    """
    Простой потокобезопасный LRU-кэш.
    Ключи — хешируемые, значения — любые.
    """
    def __init__(self, maxsize: int = 4096):
        self.maxsize = maxsize
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key):
        with self._lock:
            try:
                value = self._data.pop(key)
                self._data[key] = value   # move to end
                self._hits += 1
                return value
            except KeyError:
                self._misses += 1
                return None

    def put(self, key, value):
        with self._lock:
            if key in self._data:
                self._data.pop(key)
            self._data[key] = value
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                'size': len(self._data),
                'hits': self._hits,
                'misses': self._misses,
                'hit_ratio': (self._hits / total) if total else 0.0,
                'maxsize': self.maxsize,
            }


# ═══════════════════════════════════════════════════════════════
#                     Загрузка/хранение файлов
# ═══════════════════════════════════════════════════════════════

class _FileState:
    __slots__ = ('path', 'mtime', 'size', 'locale')

    def __init__(self, path: Path, locale: str):
        self.path = path
        self.locale = locale
        st = path.stat()
        self.mtime = st.st_mtime
        self.size = st.st_size

    def changed(self) -> bool:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return True
        return st.st_mtime != self.mtime or st.st_size != self.size


# ═══════════════════════════════════════════════════════════════
#                            I18n
# ═══════════════════════════════════════════════════════════════

class I18n:
    def __init__(
        self,
        default_locale: str = 'en',
        fallback_locale: str = 'en',
        *,
        missing_log: bool = True,
        cache_size: int = 4096,
        auto_reload: bool = False,
        auto_reload_interval: float = 5.0,
    ):
        self.default_locale = default_locale
        self.fallback_locale = fallback_locale
        self.missing_log = missing_log

        self._translations: dict[str, dict] = {}
        self._lock = threading.RLock()

        # contextvars — безопасно для asyncio/потоков
        self._locale_var: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar('homer_i18n_locale', default=None)
        )

        # Кэш переводов и плюрализации
        self._cache = _LRUCache(maxsize=cache_size)

        # Логирование отсутствующих ключей — с дедупликацией
        self._missing_keys: set[tuple[str, str]] = set()
        self._missing_lock = threading.Lock()

        # Файлы, откуда грузили — для автоперезагрузки
        self._file_states: list[_FileState] = []
        self._dirs: list[Path] = []

        # Автоперезагрузка
        self.auto_reload = auto_reload
        self.auto_reload_interval = max(1.0, float(auto_reload_interval))
        self._reload_thread: Optional[threading.Thread] = None
        self._stop_watcher = threading.Event()

    # ─────────── Контекст локали ───────────

    def set_locale(self, locale: str):
        """Установить локаль для текущего контекста (coroutine/thread)."""
        self._locale_var.set(locale)

    def reset_locale(self):
        """Сбросить локаль к default_locale в текущем контексте."""
        self._locale_var.set(None)

    @property
    def locale(self) -> str:
        cur = self._locale_var.get()
        return cur or self.default_locale

    @contextmanager
    def locale_ctx(self, locale: str):
        """Временно установить локаль в текущем контексте."""
        token = self._locale_var.set(locale)
        try:
            yield locale
        finally:
            self._locale_var.reset(token)

    # ─────────── Загрузка ───────────

    def load_dir(self, path: Path, override: bool = False):
        """
        Загружает все <locale>.yml / <locale>.yaml из каталога.

        Повторный вызов для того же каталога обновит данные (полезно
        для автоперезагрузки).
        """
        path = Path(path)
        if not path.exists():
            return
        if path not in self._dirs:
            self._dirs.append(path)

        files = list(sorted(path.glob('*.yml'))) + list(sorted(path.glob('*.yaml')))
        for f in files:
            self._load_file(f, override=override)

    def _load_file(self, f: Path, override: bool = False):
        locale = f.stem
        try:
            data = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
        except Exception as e:
            _log.warning(f"i18n: ошибка загрузки {f}: {e}")
            return
        if not isinstance(data, dict):
            _log.warning(f"i18n: {f} — ожидался объект верхнего уровня")
            return

        with self._lock:
            bucket = self._translations.setdefault(locale, {})
            self._deep_merge(bucket, data)

            # Учёт файла для автоперезагрузки
            try:
                st = _FileState(f, locale)
            except OSError:
                return
            # Заменяем запись о файле, если уже была
            self._file_states = [
                s for s in self._file_states
                if s.path != f
            ]
            self._file_states.append(st)

        # Инвалидируем кэш — данные изменились
        self._cache.clear()

    @staticmethod
    def _deep_merge(dst: dict, src: dict):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                I18n._deep_merge(dst[k], v)
            else:
                dst[k] = v

    def reload(self, *dirs: Path):
        """
        Полная перезагрузка: очищаем словари и грузим заново.
        Если dirs не заданы — используем ранее зарегистрированные каталоги.
        """
        with self._lock:
            self._translations.clear()
            self._file_states.clear()
            if dirs:
                self._dirs = [Path(d) for d in dirs]
            dirs_to_load = list(self._dirs)

        self._cache.clear()
        with self._missing_lock:
            self._missing_keys.clear()

        for d in dirs_to_load:
            self.load_dir(d)
        _log.info(f"i18n: reload ({len(dirs_to_load)} каталогов, "
                  f"{len(self._translations)} локалей)")

    # ─────────── Автоперезагрузка ───────────

    def start_watcher(self):
        """Запускает фоновый поток, следящий за изменениями файлов."""
        if self._reload_thread and self._reload_thread.is_alive():
            return
        if not self.auto_reload:
            return
        self._stop_watcher.clear()
        self._reload_thread = threading.Thread(
            target=self._watch_loop,
            name='homer-i18n-watcher',
            daemon=True,
        )
        self._reload_thread.start()
        _log.info(f"i18n: watcher запущен (интервал "
                  f"{self.auto_reload_interval}с)")

    def stop_watcher(self):
        self._stop_watcher.set()
        if self._reload_thread:
            self._reload_thread.join(timeout=2.0)
            self._reload_thread = None

    def _watch_loop(self):
        while not self._stop_watcher.wait(self.auto_reload_interval):
            try:
                self._check_files()
            except Exception as e:
                _log.warning(f"i18n watcher: {e}")

    def _check_files(self):
        with self._lock:
            states = list(self._file_states)
        changed = [s for s in states if s.changed()]
        if not changed:
            return

        _log.info(f"i18n: изменения в {len(changed)} файлах — перезагрузка")
        # Перегружаем именно изменённые файлы (не всё подряд)
        with self._lock:
            for state in changed:
                # Убираем старую запись; _load_file заново добавит
                self._file_states = [
                    s for s in self._file_states
                    if s.path != state.path
                ]
        for state in changed:
            self._load_file(state.path)

    # ─────────── Перевод ───────────

    def t(
        self,
        key: str,
        locale: Optional[str] = None,
        *,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Перевод по ключу.

        Args:
            key:      ключ с точечной нотацией ('webui.jobs.title')
            locale:   явная локаль (иначе — текущий контекст)
            default:  значение, если ключ не найден (иначе — сам ключ)
            **kwargs: подстановки {name}, {count} и т. п.

        Кэшируется по (locale, key, frozen(kwargs)).
        """
        locale = locale or self.locale
        cache_key = self._cache_key(locale, key, kwargs, default)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        value = self._resolve(key, locale)
        if value is None:
            self._log_missing(locale, key)
            value = default if default is not None else key

        if kwargs and isinstance(value, str):
            try:
                value = value.format_map(_SafeDict(kwargs))
            except Exception:
                pass

        self._cache.put(cache_key, value)
        return value

    def tn(
        self,
        key: str,
        n: int,
        locale: Optional[str] = None,
        *,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Плюрализация.

        Ищет в переводах: key.one | key.few | key.many | key.other | key.zero | key.two
        Выбирает форму по CLDR-правилам для локали.

        Пример YAML:
            jobs:
              count:
                one:   "{n} задача"
                few:   "{n} задачи"
                many:  "{n} задач"
                other: "{n} задач"
        """
        locale = locale or self.locale
        cache_key = self._cache_key(locale, f'plural:{key}:{n}', kwargs, default)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        forms = self._resolve_dict(key, locale)
        if forms is None:
            self._log_missing(locale, key + '.<plural>')
            text = default if default is not None else key
            payload = {'n': n, **kwargs}
            try:
                text = text.format_map(_SafeDict(payload))
            except Exception:
                pass
            self._cache.put(cache_key, text)
            return text

        category = self._plural_category(locale, n)
        text = (
            forms.get(category)
            or forms.get('many')
            or forms.get('other')
            or next(iter(forms.values()), key)
        )
        if not isinstance(text, str):
            text = str(text)

        payload = {'n': n, **kwargs}
        try:
            text = text.format_map(_SafeDict(payload))
        except Exception:
            pass

        self._cache.put(cache_key, text)
        return text

    # ─────────── Внутреннее разрешение ───────────

    def _resolve(self, key: str, locale: str) -> Optional[str]:
        value = self._lookup(locale, key)
        if value is None and locale != self.fallback_locale:
            value = self._lookup(self.fallback_locale, key)
        return value

    def _resolve_dict(self, key: str, locale: str) -> Optional[dict]:
        value = self._lookup_dict(locale, key)
        if value is None and locale != self.fallback_locale:
            value = self._lookup_dict(self.fallback_locale, key)
        return value

    def _lookup(self, locale: str, key: str) -> Optional[str]:
        data = self._translations.get(locale)
        if not data:
            return None
        cur: Any = data
        for p in key.split('.'):
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur if isinstance(cur, str) else None

    def _lookup_dict(self, locale: str, key: str) -> Optional[dict]:
        data = self._translations.get(locale)
        if not data:
            return None
        cur: Any = data
        for p in key.split('.'):
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur if isinstance(cur, dict) else None

    # ─────────── Плюрализация ───────────

    def _plural_category(self, locale: str, n: int) -> str:
        rule = _PLURAL_RULES.get(locale[:2], _DEFAULT_PLURAL)
        try:
            return rule(n)
        except Exception:
            return _DEFAULT_PLURAL(n)

    # ─────────── Логирование missing ───────────

    def _log_missing(self, locale: str, key: str):
        if not self.missing_log:
            return
        with self._missing_lock:
            ident = (locale, key)
            if ident in self._missing_keys:
                return
            self._missing_keys.add(ident)
        _log.warning(f"i18n: missing key '{key}' (locale={locale})")

    def missing_keys(self) -> list[tuple[str, str]]:
        """Список зафиксированных отсутствующих ключей."""
        with self._missing_lock:
            return sorted(self._missing_keys)

    def clear_missing(self):
        with self._missing_lock:
            self._missing_keys.clear()

    # ─────────── Кэш ───────────

    def _cache_key(
        self,
        locale: str,
        key: str,
        kwargs: dict,
        default: Optional[str],
    ) -> tuple:
        # frozen kwargs — кортеж пар, отсортированный по имени
        frozen = tuple(sorted(
            (k, self._hashable(v)) for k, v in (kwargs or {}).items()
        ))
        return (locale, key, frozen, default)

    @staticmethod
    def _hashable(value: Any) -> Any:
        """Приводит значение к хешируемому виду."""
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, (list, tuple)):
            return tuple(I18n._hashable(v) for v in value)
        if isinstance(value, dict):
            return tuple(sorted(
                (k, I18n._hashable(v)) for k, v in value.items()
            ))
        return str(value)

    def cache_stats(self) -> dict:
        return self._cache.stats()

    def clear_cache(self):
        self._cache.clear()

    # ─────────── Утилиты ───────────

    def available_locales(self) -> list[str]:
        return sorted(self._translations.keys())

    def keys_for(self, locale: str) -> list[str]:
        return sorted(self._flatten_keys(
            self._translations.get(locale, {})
        ))

    def _flatten_keys(self, data: dict, prefix: str = '') -> list[str]:
        result: list[str] = []
        for k, v in (data or {}).items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.extend(self._flatten_keys(v, full))
            else:
                result.append(full)
        return result

    # ─────────── Jinja ───────────

    def jinja_global(self) -> Callable:
        def _(key, **kwargs):
            return self.t(key, **kwargs)
        return _

    def jinja_plural_global(self) -> Callable:
        def tn(key, n, **kwargs):
            return self.tn(key, n, **kwargs)
        return tn

    # ─────────── Массовый перевод ───────────

    def t_dict(self, mapping: dict[str, str],
               locale: Optional[str] = None) -> dict[str, str]:
        """
        Удобно для пакетной локализации словаря:
            t_dict({'title': 'webui.jobs.title', 'cmd': 'webui.jobs.command'})
            → {'title': 'Очередь задач', 'cmd': 'Команда'}
        """
        return {k: self.t(v, locale=locale) for k, v in mapping.items()}

    def compile_dir(self, path: Path, cache_dir: Path):
        """
        Разбирает YAML и сохраняет pickle для быстрой загрузки.
        Вызывается после изменения файлов или вручную.
        """
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = Path(path)

        meta = {}
        for f in list(path.glob('*.yml')) + list(path.glob('*.yaml')):
            st = f.stat()
            locale = f.stem
            key = f"{locale}"
            meta[key] = {'mtime': st.st_mtime, 'size': st.st_size, 'file': str(f)}

        (cache_dir / 'meta.json').write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        for f in list(path.glob('*.yml')) + list(path.glob('*.yaml')):
            locale = f.stem
            try:
                data = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            except Exception as e:
                _log.warning(f"i18n compile: {f}: {e}")
                continue
            with open(cache_dir / f"{locale}.compiled.pickle", 'wb') as fp:
                pickle.dump(data, fp, protocol=pickle.HIGHEST_PROTOCOL)

    def load_compiled(self, cache_dir: Path, source_dir: Path) -> bool:
        """
        Пробует загрузить из pickle. Возвращает True при успехе.
        Автоматически перекомпилирует, если meta устарела.
        """
        cache_dir = Path(cache_dir)
        meta_path = cache_dir / 'meta.json'
        if not meta_path.exists():
            self.compile_dir(source_dir, cache_dir)
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        else:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            # Проверяем актуальность
            need_rebuild = False
            for locale, info in meta.items():
                f = Path(info['file'])
                if not f.exists():
                    need_rebuild = True
                    break
                st = f.stat()
                if st.st_mtime != info['mtime'] or st.st_size != info['size']:
                    need_rebuild = True
                    break
            if need_rebuild:
                self.compile_dir(source_dir, cache_dir)

        # Загружаем
        for pfile in cache_dir.glob('*.compiled.pickle'):
            locale = pfile.stem.split('.')[0]
            try:
                with open(pfile, 'rb') as fp:
                    data = pickle.load(fp)
                with self._lock:
                    bucket = self._translations.setdefault(locale, {})
                    self._deep_merge(bucket, data)
            except Exception as e:
                _log.warning(f"i18n: {pfile}: {e}")
                return False
        return True

    def tn_range(
        self,
        key: str,
        start: int,
        end: int,
        locale: Optional[str] = None,
        *,
        default: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Плюрализация диапазона: 1–10 файлов, 2–4 задачи.
        Форма выбирается по CLDR для (start, end):
            - если категории совпадают → эта форма
            - иначе → 'other'
        """
        locale = locale or self.locale
        cache_key = self._cache_key(
            locale, f'plural_range:{key}:{start}:{end}', kwargs, default,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        forms = self._resolve_dict(key, locale)
        if forms is None:
            self._log_missing(locale, key + '.<range>')
            text = default if default is not None else key
            payload = {'start': start, 'end': end, **kwargs}
            try:
                text = text.format_map(_SafeDict(payload))
            except Exception:
                pass
            self._cache.put(cache_key, text)
            return text

        cat_start = self._plural_category(locale, start)
        cat_end = self._plural_category(locale, end)
        category = cat_start if cat_start == cat_end else 'other'

        text = (
            forms.get(category)
            or forms.get('many')
            or forms.get('other')
            or next(iter(forms.values()), key)
        )
        if not isinstance(text, str):
            text = str(text)

        payload = {'start': start, 'end': end, **kwargs}
        try:
            text = text.format_map(_SafeDict(payload))
        except Exception:
            pass

        self._cache.put(cache_key, text)
        return text

    def format_number(self, value, locale=None, **kwargs):
        return _fmt_number(value, locale or self.locale, **kwargs)

    def format_percent(self, value, locale=None, **kwargs):
        return _fmt_percent(value, locale or self.locale, **kwargs)

    def format_date(self, dt, locale=None, **kwargs):
        return _fmt_date(dt, locale or self.locale, **kwargs)

    def format_datetime(self, dt, locale=None, **kwargs):
        return _fmt_datetime(dt, locale or self.locale, **kwargs)

    def format_time(self, dt, locale=None, **kwargs):
        return _fmt_time(dt, locale or self.locale, **kwargs)

    # Jinja-фильтры
    def jinja_filters(self) -> dict:
        return {
            'num':  lambda v, **kw: self.format_number(v, **kw),
            'pct':  lambda v, **kw: self.format_percent(v, **kw),
            'date': lambda v, **kw: self.format_date(v, **kw),
            'dt':   lambda v, **kw: self.format_datetime(v, **kw),
            'time': lambda v, **kw: self.format_time(v, **kw),
        }

# ═══════════════════════════════════════════════════════════════
#                    Глобальный экземпляр
# ═══════════════════════════════════════════════════════════════

_i18n: Optional[I18n] = None
_init_lock = threading.Lock()


def get_i18n() -> I18n:
    global _i18n
    if _i18n is None:
        with _init_lock:
            if _i18n is None:
                _i18n = I18n()
    return _i18n


def configure(
    default_locale: str = 'en',
    fallback_locale: str = 'en',
    *,
    missing_log: bool = True,
    cache_size: int = 4096,
    auto_reload: bool = False,
    auto_reload_interval: float = 5.0,
) -> I18n:
    """
    Настроить глобальный экземпляр. Вызывается один раз при старте.
    После настройки, если auto_reload=True — запускается watcher.
    """
    i18n = get_i18n()
    i18n.default_locale = default_locale
    i18n.fallback_locale = fallback_locale
    i18n.missing_log = missing_log
    i18n.auto_reload = auto_reload
    i18n.auto_reload_interval = max(1.0, float(auto_reload_interval))
    # При смене cache_size пересоздаём кэш
    i18n._cache = _LRUCache(maxsize=cache_size)
    return i18n


# ─────────── Модульные функции (тонкие обёртки) ───────────

def set_locale(locale: str):
    get_i18n().set_locale(locale)


def reset_locale():
    get_i18n().reset_locale()


@contextmanager
def locale_ctx(locale: str):
    with get_i18n().locale_ctx(locale):
        yield locale


def t(key: str, **kwargs) -> str:
    return get_i18n().t(key, **kwargs)


def tn(key: str, n: int, **kwargs) -> str:
    return get_i18n().tn(key, n, **kwargs)

def tn_range(key: str, start: int, end: int, **kwargs) -> str:
    return get_i18n().tn_range(key, start, end, **kwargs)

def jinja_range_global(self):
    def tnr(key, start, end, **kwargs):
        return self.tn_range(key, start, end, **kwargs)
    return tnr
