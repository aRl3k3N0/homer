"""
Система плагинов Homer в стиле WordPress.

Публичный API:
    PluginManager — менеджер (обнаружение, загрузка, миграции)
    PluginInfo    — метаданные плагина
    get_manager() — глобальный экземпляр менеджера
"""
from .manager import PluginManager, get_manager
from .plugin import PluginInfo, PluginState

__all__ = ['PluginManager', 'get_manager', 'PluginInfo', 'PluginState']
