"""
Работа с конфигурацией
"""
from __future__ import annotations
import yaml
from pathlib import Path
from typing import Any, Optional


class Config:
    config_path: Path
    _data: dict[str, Any]

    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self._data = {}
        self.load()

    def load(self):
        if not self.config_path.exists():
            self._data = {}
            return
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._data = yaml.safe_load(f) or {}
        except Exception as e:
            raise RuntimeError(f"Ошибка загрузки конфигурации: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def all(self) -> dict[str, Any]:
        return self._data

    def __getitem__(self, key):
        return self.get(key)

    def __contains__(self, key):
        return self.get(key) is not None