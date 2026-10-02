"""
Marketplace-реестр плагинов.

Источники:
    - URL (https://...)
    - локальный файл (registry.json)

Кэширование:
    - var/cache/plugins-registry.json
    - TTL из config.yml → plugins.registry_ttl (по умолчанию 3600 секунд)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Optional
import urllib.request

from .deps import parse_version


class RegistryError(Exception):
    pass


@dataclass
class RegistryVersion:
    version: str
    url: str
    checksum: Optional[str] = None
    signature_key_id: Optional[str] = None
    requires_homer: str = ''
    requires: list[str] = field(default_factory=list)
    changelog: str = ''
    released_at: Optional[str] = None
    min_db_driver: Optional[str] = None


@dataclass
class RegistryPlugin:
    name: str
    description: str = ''
    author: str = ''
    homepage: str = ''
    tags: list[str] = field(default_factory=list)
    versions: list[RegistryVersion] = field(default_factory=list)

    def latest(self) -> Optional[RegistryVersion]:
        if not self.versions:
            return None
        return max(self.versions, key=lambda v: parse_version(v.version))

    def find(self, version: str) -> Optional[RegistryVersion]:
        for v in self.versions:
            if v.version == version:
                return v
        return None


class Registry:
    def __init__(self, root_dir: Path, url_or_path: str, cache_ttl: int = 3600):
        self.root = Path(root_dir)
        self.source = url_or_path
        self.cache_ttl = cache_ttl
        self.cache_path = self.root / 'var' / 'cache' / 'plugins-registry.json'
        self._data: Optional[dict] = None

    # ─────────── Загрузка ───────────

    def load(self, force_refresh: bool = False) -> dict:
        if self._data is not None and not force_refresh:
            return self._data

        # Из кэша
        if not force_refresh and self._is_cache_fresh():
            try:
                self._data = json.loads(self.cache_path.read_text(encoding='utf-8'))
                return self._data
            except Exception:
                pass

        # Из источника
        raw = self._fetch()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RegistryError(f"registry.json: невалидный JSON: {e}")

        self._validate(data)
        self._data = data

        # В кэш
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except Exception:
            pass

        return data

    def _fetch(self) -> str:
        if self.source.startswith(('http://', 'https://')):
            try:
                with urllib.request.urlopen(self.source, timeout=30) as r:
                    return r.read().decode('utf-8')
            except Exception as e:
                # Попробуем кэш, даже устаревший
                if self.cache_path.exists():
                    return self.cache_path.read_text(encoding='utf-8')
                raise RegistryError(f"Не удалось загрузить {self.source}: {e}")
        p = Path(self.source).expanduser()
        if not p.exists():
            raise RegistryError(f"Файл реестра не найден: {p}")
        return p.read_text(encoding='utf-8')

    def _is_cache_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        age = time.time() - self.cache_path.stat().st_mtime
        return age < self.cache_ttl

    def _validate(self, data: dict):
        if not isinstance(data, dict):
            raise RegistryError("registry.json: ожидался объект верхнего уровня")
        if 'plugins' not in data or not isinstance(data['plugins'], list):
            raise RegistryError("registry.json: нет ключа 'plugins' (список)")

    # ─────────── API ───────────

    def list_plugins(
        self, tag: Optional[str] = None, search: Optional[str] = None
    ) -> list[RegistryPlugin]:
        data = self.load()
        result = []
        for p in data.get('plugins', []):
            if tag and tag not in (p.get('tags') or []):
                continue
            if search:
                hay = (p.get('name', '') + ' ' + p.get('description', '')).lower()
                if search.lower() not in hay:
                    continue
            result.append(self._to_plugin(p))
        return result

    def get_plugin(self, name: str) -> Optional[RegistryPlugin]:
        data = self.load()
        for p in data.get('plugins', []):
            if p.get('name') == name:
                return self._to_plugin(p)
        return None

    @staticmethod
    def _to_plugin(p: dict) -> RegistryPlugin:
        versions = [
            RegistryVersion(
                version=v.get('version', ''),
                url=v.get('url', ''),
                checksum=v.get('checksum'),
                signature_key_id=v.get('signature_key_id'),
                requires_homer=v.get('requires_homer', ''),
                requires=v.get('requires', []) or [],
                changelog=v.get('changelog', ''),
                released_at=v.get('released_at'),
                min_db_driver=v.get('min_db_driver'),
            )
            for v in p.get('versions', [])
        ]
        return RegistryPlugin(
            name=p.get('name', ''),
            description=p.get('description', ''),
            author=p.get('author', ''),
            homepage=p.get('homepage', ''),
            tags=p.get('tags', []) or [],
            versions=versions,
        )
