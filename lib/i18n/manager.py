from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

import yaml


_log = logging.getLogger('homer.i18n')


class I18n:
    def __init__(self, default_locale: str = 'en',
                 fallback_locale: str = 'en'):
        self.default_locale = default_locale
        self.fallback_locale = fallback_locale
        self._translations: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._local = threading.local()   # per-thread текущая локаль

    # ─────────── Загрузка ───────────

    def load_dir(self, path: Path, override: bool = False):
        """
        Загружает все <locale>.yml из каталога.
        При override=True переопределяет существующие ключи.
        """
        path = Path(path)
        if not path.exists():
            return
        for f in sorted(path.glob('*.yml')) + sorted(path.glob('*.yaml')):
            locale = f.stem
            try:
                data = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            except Exception as e:
                _log.warning(f"i18n: ошибка загрузки {f}: {e}")
                continue
            with self._lock:
                if override or locale not in self._translations:
                    self._translations.setdefault(locale, {})
                self._deep_merge(self._translations[locale], data)

    @staticmethod
    def _deep_merge(dst: dict, src: dict):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                I18n._deep_merge(dst[k], v)
            else:
                dst[k] = v

    # ─────────── Локаль ───────────

    def set_locale(self, locale: str):
        with self._lock:
            self._local.locale = locale

    @property
    def locale(self) -> str:
        return getattr(self._local, 'locale', self.default_locale)

    # ─────────── Перевод ───────────

    def t(self, key: str, locale: Optional[str] = None, **kwargs) -> str:
        locale = locale or self.locale
        with self._lock:
            value = self._lookup(locale, key)
            if value is None and locale != self.fallback_locale:
                value = self._lookup(self.fallback_locale, key)
            if value is None:
                return key  # ключ как есть
        if kwargs and isinstance(value, str):
            try:
                return value.format(**kwargs)
            except (KeyError, ValueError):
                return value
        return value

    def _lookup(self, locale: str, key: str) -> Optional[str]:
        data = self._translations.get(locale)
        if not data:
            return None
        parts = key.split('.')
        cur = data
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur if isinstance(cur, str) else None

    # ─────────── Список доступных локалей ───────────

    def available_locales(self) -> list[str]:
        return sorted(self._translations.keys())

    # ─────────── Поддержка для Jinja ───────────

    def jinja_global(self):
        """Возвращает callable для использования в шаблонах."""
        def _(key, **kwargs):
            return self.t(key, **kwargs)
        return _


# ─────────── Глобальный экземпляр ───────────

_i18n: Optional[I18n] = None


def get_i18n() -> I18n:
    global _i18n
    if _i18n is None:
        _i18n = I18n()
    return _i18n


def set_locale(locale: str):
    get_i18n().set_locale(locale)


def t(key: str, **kwargs) -> str:
    return get_i18n().t(key, **kwargs)
