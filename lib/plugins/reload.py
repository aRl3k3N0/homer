"""
Hot-reload плагинов без перезапуска Homer.

Что делает:
    1. Вызывает plugin_disable(context) у старого модуля (если есть).
    2. Удаляет модуль плагина и все его подмодули из sys.modules.
    3. Удаляет зарегистрированные команды, нотификаторы, шаблоны, переводы.
    4. Перечитывает plugin.json (мог измениться).
    5. Импортирует __init__.py заново.
    6. Вызывает plugin_init(context).
    7. Перерегистрирует команды.
    8. Переприменяет миграции (если auto_migrate).

Ограничения:
    - Уже запущенные команды продолжают работать со старым кодом
      (потоки не перезапускаются).
    - Глобальные side-effects плагина (например, monkey-patch) остаются
      с прежней версией, если не отменены в plugin_disable.
    - Классы/функции, сохранённые где-то в переменных, не обновятся.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Optional

from .plugin import PluginInfo, PluginState


_log = logging.getLogger('homer.plugins.reload')


class PluginReloader:
    def __init__(self, manager, root_dir: Path, config, homer_context: dict):
        self.mgr = manager
        self.root_dir = Path(root_dir)
        self.config = config
        self.context = homer_context
        # Внешние реестры, куда плагины могут писать
        self._registries = self._collect_registries()

    def _collect_registries(self) -> dict:
        """Собирает доступные «внешние» реестры, которые чистятся."""
        regs = {}
        try:
            from lib.notify import REGISTRY as notify_registry
            regs['notify'] = notify_registry
        except Exception:
            pass
        return regs

    # ─────────── Публичный API ───────────

    def reload(self, plugin_name: str) -> bool:
        info = self.mgr.get(plugin_name)
        if info is None:
            _log.warning(f"reload: плагин '{plugin_name}' не найден")
            return False

        _log.info(f"reload: перезагрузка '{plugin_name}'")

        # 1. Выгружаем
        self._unload(info)

        # 2. Перечитываем манифест
        try:
            new_info = PluginInfo.from_dir(info.path)
        except Exception as e:
            _log.error(f"reload: манифест '{plugin_name}' сломан: {e}")
            info.state = PluginState.ERROR
            info.error = str(e)
            return False

        # Сохраняем состояние
        new_info.state = PluginState.DISCOVERED
        self.mgr._plugins[plugin_name] = new_info

        # 3. Загружаем заново
        try:
            self.mgr._initialized.discard(plugin_name)
            self.mgr._load_one(new_info, self.context)
        except Exception as e:
            _log.error(f"reload: ошибка загрузки '{plugin_name}': {e}",
                       exc_info=True)
            return False

        if new_info.state == PluginState.ERROR:
            _log.error(f"reload: '{plugin_name}' в состоянии error: "
                       f"{new_info.error}")
            return False

        # 4. Миграции
        if self.config.get('plugins.auto_migrate', True):
            try:
                from lib.db import connect
                sched_cfg = self.config.get('scheduler', {}) or {}
                driver = sched_cfg.get('storage', 'sqlite')
                conn_cfg = (sched_cfg.get(driver)
                            or self.config.get(f'databases.{driver}'))
                if driver == 'sqlite':
                    if not conn_cfg:
                        conn_cfg = {'path': 'var/scheduler.db'}
                    elif 'path' not in conn_cfg:
                        conn_cfg = dict(conn_cfg, path='var/scheduler.db')
                db = connect(driver, conn_cfg)
                try:
                    self.mgr.run_migrations(driver, db)
                finally:
                    db.close()
            except Exception as e:
                _log.warning(f"reload: миграции '{plugin_name}': {e}")

        _log.info(f"reload: '{plugin_name}' перезагружен "
                  f"(v{new_info.version})")
        return True

    def reload_all(self) -> dict[str, bool]:
        result = {}
        for name in list(self.mgr._plugins.keys()):
            result[name] = self.reload(name)
        return result

    # ─────────── Внутреннее ───────────

    def _unload(self, info: PluginInfo):
        # 1. Вызываем plugin_disable, если есть
        module = self._get_module(info.name)
        if module is not None:
            for hook in ('plugin_disable', 'plugin_unload', 'plugin_shutdown'):
                fn = getattr(module, hook, None)
                if callable(fn):
                    try:
                        fn(self.context)
                    except Exception as e:
                        _log.warning(f"reload: {hook} '{info.name}': {e}")
                    break

        # 2. Удаляем все модули плагина из sys.modules
        prefix = f"homer_plugin_{info.name}"
        for mod_name in list(sys.modules.keys()):
            if mod_name == prefix or mod_name.startswith(prefix + '.'):
                try:
                    del sys.modules[mod_name]
                except KeyError:
                    pass

        # 3. Убираем команды плагина из любого кеша (если используется)
        try:
            from lib.command_loader import CommandLoader
            # Ничего делать не нужно — loader перечитывает каждый раз.
            pass
        except Exception:
            pass

        # 4. Чистим нотификаторы, зарегистрированные плагином
        try:
            from lib.notify import REGISTRY as notify_registry
            to_remove = []
            for reg_name, cls in notify_registry.items():
                mod = getattr(cls, '__module__', '') or ''
                if mod.startswith(prefix):
                    to_remove.append(reg_name)
            for reg_name in to_remove:
                notify_registry.pop(reg_name, None)
                _log.info(f"reload: удалён нотификатор '{reg_name}'")
        except Exception:
            pass

        # 5. Убираем пути плагина из sys.path (на случай, если плагин сам
        #    их регистрировал — здесь только базовый путь)
        path = str(info.path)
        while path in sys.path:
            sys.path.remove(path)

        # 6. Отмечаем
        self.mgr._initialized.discard(info.name)

    def _get_module(self, plugin_name: str):
        return sys.modules.get(f"homer_plugin_{plugin_name}")
