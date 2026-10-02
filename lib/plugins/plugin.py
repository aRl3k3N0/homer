"""
Метаданные и состояние плагина.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Optional


class PluginState:
    DISCOVERED = 'discovered'  # найден, но не загружен
    LOADED = 'loaded'  # __init__.py успешно выполнен
    ENABLED = 'enabled'  # включён в config.yml
    DISABLED = 'disabled'  # выключен в config.yml
    ERROR = 'error'  # ошибка загрузки/инициализации
    MIGRATED = 'migrated'  # миграции применены


@dataclass
class PluginInfo:
    """Метаданные плагина из plugin.json."""

    name: str
    version: str = '0.0.0'
    description: str = ''
    author: str = ''
    homepage: str = ''
    requires: list[str] = field(default_factory=list)
    requires_homer: str = '>=1.0.0'
    auto_migrate: bool = True
    path: Optional[Path] = None
    state: str = PluginState.DISCOVERED
    error: Optional[str] = None

    @classmethod
    def from_dir(cls, plugin_dir: Path) -> PluginInfo:
        manifest = plugin_dir / 'plugin.json'
        if not manifest.exists():
            raise FileNotFoundError(f"Нет plugin.json в {plugin_dir}")
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if 'name' not in data:
            raise ValueError(f"plugin.json: отсутствует поле 'name' ({plugin_dir})")
        return cls(
            name=data['name'],
            version=data.get('version', '0.0.0'),
            description=data.get('description', ''),
            author=data.get('author', ''),
            homepage=data.get('homepage', ''),
            requires=data.get('requires', []),
            requires_homer=data.get('requires_homer', '>=1.0.0'),
            auto_migrate=data.get('auto_migrate', True),
            path=plugin_dir,
        )

    # Удобные пути
    @property
    def commands_dir(self) -> Optional[Path]:
        p = self.path / 'commands'
        return p if p.exists() else None

    @property
    def lib_dir(self) -> Optional[Path]:
        p = self.path / 'lib'
        return p if p.exists() else None

    @property
    def email_dir(self) -> Optional[Path]:
        p = self.path / 'email'
        return p if p.exists() else None

    @property
    def langs_dir(self) -> Optional[Path]:
        p = self.path / 'langs'
        return p if p.exists() else None

    @property
    def templates_dir(self) -> Optional[Path]:
        p = self.path / 'templates'
        return p if p.exists() else None

    @property
    def static_dir(self) -> Optional[Path]:
        p = self.path / 'static'
        return p if p.exists() else None

    @property
    def migrations_dir(self) -> Optional[Path]:
        p = self.path / 'migrations'
        return p if p.exists() else None

    def migrations_for(self, driver: str) -> Optional[Path]:
        """Каталог миграций под конкретный драйвер БД."""
        if not self.migrations_dir:
            return None
        d = self.migrations_dir / driver
        return d if d.exists() else None
