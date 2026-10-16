"""
i18n subsystem for Homer.

Loading order (weakest to strongest):
    1. system   -- lib/webui/i18n      (shipped with the core)
    2. project  -- <project>/langs
    3. plugin   -- <project>/plugins/<name>/langs

Each subsequent layer overrides keys from previous ones.

Features:
    - YAML translations with nested keys ('webui.nav.jobs')
    - fallback on fallback_locale
    - pluralization (CLDR rules: ru, en, de, fr, uk, pl, cs, es, it, ar)
    - contextvars-based locale: safe for asyncio and threads
    - LRU cache for translations and pluralization
    - auto-reload when source files change (optional)
    - missing keys are logged once (deduplication)
    - Jinja globals: `_` and `tn`
    - explicit layer tracking: system / project / plugin
"""

from __future__ import annotations

import contextvars
import logging
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

_log = logging.getLogger("homer.i18n")


# ═══════════════════════════════════════════════════════════════
#                    CLDR plural rules
# ═══════════════════════════════════════════════════════════════

_PLURAL_RULES: dict[str, Callable[[int], str]] = {
    "en": lambda n: "one" if n == 1 else "other",
    "de": lambda n: "one" if n == 1 else "other",
    "nl": lambda n: "one" if n == 1 else "other",
    "sv": lambda n: "one" if n == 1 else "other",
    "da": lambda n: "one" if n == 1 else "other",
    "it": lambda n: "one" if n == 1 else "other",
    "es": lambda n: "one" if n == 1 else "other",
    "pt": lambda n: "one" if n == 1 else "other",
    "fr": lambda n: "one" if n in (0, 1) else "other",
    "ja": lambda n: "other",
    "zh": lambda n: "other",
    "ko": lambda n: "other",
    "tr": lambda n: "other",
    "ru": lambda n: (
        "one" if (n % 10 == 1 and n % 100 != 11)
        else "few" if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else "many"
    ),
    "uk": lambda n: (
        "one" if (n % 10 == 1 and n % 100 != 11)
        else "few" if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else "many"
    ),
    "be": lambda n: (
        "one" if (n % 10 == 1 and n % 100 != 11)
        else "few" if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else "many"
    ),
    "pl": lambda n: (
        "one" if n == 1
        else "few" if (2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14)
        else "many"
    ),
    "cs": lambda n: (
        "one" if n == 1
        else "few" if 2 <= n <= 4
        else "many"
    ),
    "sk": lambda n: (
        "one" if n == 1
        else "few" if 2 <= n <= 4
        else "many"
    ),
    "lt": lambda n: (
        "one" if (n % 10 == 1 and n % 100 != 11)
        else "few" if (2 <= n % 10 <= 9 and not 11 <= n % 100 <= 19)
        else "many"
    ),
    "ar": lambda n: (
        "zero" if n == 0
        else "one" if n == 1
        else "two" if n == 2
        else "few" if 3 <= n % 100 <= 10
        else "many" if 11 <= n % 100 <= 99
        else "other"
    ),
}

_DEFAULT_PLURAL = _PLURAL_RULES["en"]


# ═══════════════════════════════════════════════════════════════
#                    Safe string formatting
# ═══════════════════════════════════════════════════════════════

class _SafeDict(dict):
    """
    dict that does not raise on missing format keys.
    The literal placeholder is returned instead, e.g. `{user}`.
    """
    def __missing__(self, key):
        return "{" + key + "}"


# ═══════════════════════════════════════════════════════════════
#                            LRU cache
# ═══════════════════════════════════════════════════════════════

class _LRUCache:
    """Thread-safe LRU cache for translation results."""

    def __init__(self, maxsize: int = 4096):
        self.maxsize = maxsize
        self._data: "OrderedDict[Any, Any]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key):
        with self._lock:
            try:
                value = self._data.pop(key)
                self._data[key] = value
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
                "size": len(self._data),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": (self._hits / total) if total else 0.0,
                "maxsize": self.maxsize,
            }


# ═══════════════════════════════════════════════════════════════
#                          Load layers
# ═══════════════════════════════════════════════════════════════

class Layer:
    """Layer identifiers. Ordered from weakest to strongest."""
    SYSTEM = "system"
    PROJECT = "project"
    PLUGIN = "plugin"

    ORDER = [SYSTEM, PROJECT, PLUGIN]


# ═══════════════════════════════════════════════════════════════
#                            I18n
# ═══════════════════════════════════════════════════════════════

class I18n:
    def __init__(
        self,
        default_locale: str = "en",
        fallback_locale: str = "en",
        *,
        missing_log: bool = True,
        cache_size: int = 4096,
    ):
        self.default_locale = default_locale
        self.fallback_locale = fallback_locale
        self.missing_log = missing_log

        self._translations: dict[str, dict] = {}
        self._lock = threading.RLock()

        # Locale context: safe for asyncio and threads
        self._locale_var: contextvars.ContextVar[Optional[str]] = (
            contextvars.ContextVar("homer_i18n_locale", default=None)
        )

        # Cache
        self._cache = _LRUCache(maxsize=cache_size)

        # Missing keys deduplication
        self._missing_keys: set[tuple[str, str]] = set()
        self._missing_lock = threading.Lock()

        # Registered directories by layer, in the order added
        self._dirs: dict[str, list[Path]] = {
            Layer.SYSTEM: [],
            Layer.PROJECT: [],
            Layer.PLUGIN: [],
        }

        # History: (path, layer) for diagnostics
        self._history: list[tuple[Path, str]] = []

    # ─────────── Locale context ───────────

    def set_locale(self, locale: str) -> None:
        self._locale_var.set(locale)

    def reset_locale(self) -> None:
        self._locale_var.set(None)

    @property
    def locale(self) -> str:
        cur = self._locale_var.get()
        return cur or self.default_locale

    @contextmanager
    def locale_ctx(self, locale: str):
        token = self._locale_var.set(locale)
        try:
            yield locale
        finally:
            self._locale_var.reset(token)

    # ─────────── Loading ───────────

    def load_dir(self, path: Path, *, layer: str = Layer.PROJECT,
                 override: bool = True) -> None:
        """
        Load all <locale>.yml / <locale>.yaml from a directory.

        `layer` is used for diagnostics and reload ordering.
        `override=True` means keys overwrite existing ones (later layer
        wins). `override=False` only adds missing keys.
        """
        path = Path(path)
        if not path.exists():
            return

        # Register for reload (avoid duplicates)
        if path not in self._dirs[layer]:
            self._dirs[layer].append(path)
        self._history.append((path, layer))

        files = sorted(path.glob("*.yml")) + sorted(path.glob("*.yaml"))
        for f in files:
            self._load_file(f, layer=layer, override=override)

    def _load_file(self, f: Path, *, layer: str, override: bool) -> None:
        locale = f.stem
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception as e:
            _log.warning("i18n: failed to load %s: %s", f, e)
            return

        if not isinstance(data, dict):
            _log.warning("i18n: %s top-level is not a mapping", f)
            return

        with self._lock:
            bucket = self._translations.setdefault(locale, {})
            if override:
                self._deep_merge(bucket, data)
            else:
                self._deep_merge_missing(bucket, data)

        _log.debug("i18n: loaded %s (%s, locale=%s)", f, layer, locale)
        self._cache.clear()

    @staticmethod
    def _deep_merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                I18n._deep_merge(dst[k], v)
            else:
                dst[k] = v

    @staticmethod
    def _deep_merge_missing(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                I18n._deep_merge_missing(dst[k], v)
            elif k not in dst:
                dst[k] = v

    # ─────────── Reload ───────────

    def reload(self) -> None:
        """
        Reload all previously registered directories in the correct
        order: system → project → plugin.
        """
        _log.info("i18n: reload requested")
        with self._lock:
            self._translations.clear()
        self._cache.clear()
        with self._missing_lock:
            self._missing_keys.clear()

        for layer in Layer.ORDER:
            for d in self._dirs[layer]:
                if not d.exists():
                    continue
                for f in sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml")):
                    self._load_file(f, layer=layer, override=True)

    def sources(self) -> dict[str, list[str]]:
        """Return {layer: [paths]} for diagnostics."""
        return {
            layer: [str(p) for p in dirs]
            for layer, dirs in self._dirs.items()
        }

    def key_source(self, locale: str, key: str) -> Optional[str]:
        """
        Return the layer that provided the given key, or None.
        NOTE: O(files) -- for diagnostics only, not for hot paths.
        """
        for path, layer in reversed(self._history):
            for f in path.glob("*.yml"):
                if f.stem != locale:
                    continue
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                cur: Any = data
                for part in key.split("."):
                    if not isinstance(cur, dict) or part not in cur:
                        cur = None
                        break
                    cur = cur[part]
                if isinstance(cur, str):
                    return layer
        return None

    # ─────────── Translation ───────────

    def t(self, key: str, locale: Optional[str] = None, *,
          default: Optional[str] = None, **kwargs: Any) -> str:
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

    def tn(self, key: str, n: int, locale: Optional[str] = None, *,
           default: Optional[str] = None, **kwargs: Any) -> str:
        locale = locale or self.locale
        cache_key = self._cache_key(locale, f"plural:{key}:{n}", kwargs, default)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        forms = self._resolve_dict(key, locale)
        if forms is None:
            self._log_missing(locale, key + ".<plural>")
            text = default if default is not None else key
            payload = {"n": n, **kwargs}
            try:
                text = text.format_map(_SafeDict(payload))
            except Exception:
                pass
            self._cache.put(cache_key, text)
            return text

        category = self._plural_category(locale, n)
        text = (
            forms.get(category)
            or forms.get("many")
            or forms.get("other")
            or next(iter(forms.values()), key)
        )
        if not isinstance(text, str):
            text = str(text)

        payload = {"n": n, **kwargs}
        try:
            text = text.format_map(_SafeDict(payload))
        except Exception:
            pass

        self._cache.put(cache_key, text)
        return text

    # ─────────── Internal resolve ───────────

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
        for p in key.split("."):
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur if isinstance(cur, str) else None

    def _lookup_dict(self, locale: str, key: str) -> Optional[dict]:
        data = self._translations.get(locale)
        if not data:
            return None
        cur: Any = data
        for p in key.split("."):
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur if isinstance(cur, dict) else None

    # ─────────── Plural ───────────

    def _plural_category(self, locale: str, n: int) -> str:
        rule = _PLURAL_RULES.get(locale[:2], _DEFAULT_PLURAL)
        try:
            return rule(n)
        except Exception:
            return _DEFAULT_PLURAL(n)

    # ─────────── Missing keys ───────────

    def _log_missing(self, locale: str, key: str) -> None:
        if not self.missing_log:
            return
        with self._missing_lock:
            ident = (locale, key)
            if ident in self._missing_keys:
                return
            self._missing_keys.add(ident)
        _log.warning("i18n: missing key '%s' (locale=%s)", key, locale)

    def missing_keys(self) -> list[tuple[str, str]]:
        with self._missing_lock:
            return sorted(self._missing_keys)

    def clear_missing(self) -> None:
        with self._missing_lock:
            self._missing_keys.clear()

    # ─────────── Cache ───────────

    def _cache_key(self, locale: str, key: str, kwargs: dict,
                   default: Optional[str]) -> tuple:
        frozen = tuple(sorted(
            (k, self._hashable(v)) for k, v in (kwargs or {}).items()
        ))
        return (locale, key, frozen, default)

    @staticmethod
    def _hashable(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, (list, tuple)):
            return tuple(I18n._hashable(v) for v in value)
        if isinstance(value, dict):
            return tuple(sorted((k, I18n._hashable(v)) for k, v in value.items()))
        return str(value)

    def cache_stats(self) -> dict:
        return self._cache.stats()

    def clear_cache(self) -> None:
        self._cache.clear()

    # ─────────── Utilities ───────────

    def available_locales(self) -> list[str]:
        return sorted(self._translations.keys())

    def keys_for(self, locale: str) -> list[str]:
        return sorted(self._flatten_keys(self._translations.get(locale, {})))

    def _flatten_keys(self, data: dict, prefix: str = "") -> list[str]:
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

    def jinja_filters(self) -> dict:
        from .formatting import (
            format_number, format_percent, format_date,
            format_datetime, format_time,
        )
        return {
            "num":  lambda v, **kw: format_number(v, self.locale, **kw),
            "pct":  lambda v, **kw: format_percent(v, self.locale, **kw),
            "date": lambda v, **kw: format_date(v, self.locale, **kw),
            "dt":   lambda v, **kw: format_datetime(v, self.locale, **kw),
            "time": lambda v, **kw: format_time(v, self.locale, **kw),
        }


# ═══════════════════════════════════════════════════════════════
#                    Global instance
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
    default_locale: str = "en",
    fallback_locale: str = "en",
    *,
    missing_log: bool = True,
    cache_size: int = 4096,
) -> I18n:
    i18n = get_i18n()
    i18n.default_locale = default_locale
    i18n.fallback_locale = fallback_locale
    i18n.missing_log = missing_log
    i18n._cache = _LRUCache(maxsize=cache_size)
    return i18n


def set_locale(locale: str) -> None:
    get_i18n().set_locale(locale)


def reset_locale() -> None:
    get_i18n().reset_locale()


@contextmanager
def locale_ctx(locale: str):
    with get_i18n().locale_ctx(locale):
        yield locale


def t(key: str, **kwargs) -> str:
    return get_i18n().t(key, **kwargs)


def tn(key: str, n: int, **kwargs) -> str:
    return get_i18n().tn(key, n, **kwargs)
