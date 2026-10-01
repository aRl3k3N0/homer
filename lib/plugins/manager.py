"""
Менеджер плагинов: обнаружение, загрузка, миграции, объединение ресурсов.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Optional

from .plugin import PluginInfo, PluginState


_log = logging.getLogger('homer.plugins')


class PluginManager:
    """
    Менеджер плагинов Homer.

    Использование:
        pm = get_manager()
        pm.discover(root_dir / 'plugins', config)
        pm.load_all()
        pm.run_migrations(driver='sqlite')
    """

    def __init__(self):
        self._plugins: dict[str, PluginInfo] = {}
        self._root: Optional[Path] = None
        self._config = None
        self._initialized: set[str] = set()

    # ─────────── Обнаружение ───────────

    def discover(self, plugins_dir: Path, config=None) -> list[PluginInfo]:
        """
        Сканирует каталог plugins/ и возвращает список плагинов
        (не загружая их).
        """
        self._root = Path(plugins_dir)
        self._config = config
        self._plugins.clear()

        if not self._root.exists():
            return []

        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(('.', '_')):
                continue
            manifest = entry / 'plugin.json'
            if not manifest.exists():
                continue
            try:
                info = PluginInfo.from_dir(entry)
            except Exception as e:
                _log.warning(f"Плагин '{entry.name}' пропущен: {e}")
                continue
            self._plugins[info.name] = info
        return list(self._plugins.values())

    # ─────────── Загрузка ───────────

    def load_all(self, context: dict | None = None):
        """
        Загружает включённые плагины:
            - импортирует __init__.py плагина;
            - вызывает plugin_init(context), если есть;
            - помечает состояние.
        """
        enabled = self._enabled_names()

        for name, info in self._plugins.items():
            if name not in enabled:
                info.state = PluginState.DISABLED
                continue
            if name in self._initialized:
                continue
            self._load_one(info, context)

    def _load_one(self, info: PluginInfo, context: dict | None):
        try:
            module = self._import_plugin(info)
            info.state = PluginState.LOADED

            init = getattr(module, 'plugin_init', None)
            if callable(init):
                try:
                    init(context or {})
                except Exception as e:
                    info.state = PluginState.ERROR
                    info.error = f"plugin_init: {e}"
                    _log.error(f"Плагин '{info.name}' init error: {e}",
                               exc_info=True)
                    return

            info.state = PluginState.ENABLED
            self._initialized.add(info.name)
            _log.info(f"Плагин '{info.name}' v{info.version} загружен")
        except Exception as e:
            info.state = PluginState.ERROR
            info.error = str(e)
            _log.error(f"Ошибка загрузки плагина '{info.name}': {e}",
                       exc_info=True)

    def _import_plugin(self, info: PluginInfo):
        """Импортирует plugins/<name>/__init__.py как модуль."""
        init_py = info.path / '__init__.py'
        if not init_py.exists():
            # Создаём пустой модуль-заглушку, чтобы не падать
            module_name = f"homer_plugin_{info.name}"
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            return module

        module_name = f"homer_plugin_{info.name}"
        spec = importlib.util.spec_from_file_location(module_name, init_py)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        # Позволяем плагину писать `from . import ...`
        package_path = str(info.path)
        if package_path not in sys.path:
            sys.path.insert(0, package_path)
        spec.loader.exec_module(module)
        return module

    # ─────────── Реестр включённых ───────────

    def _enabled_names(self) -> set[str]:
        if self._config is None:
            return set(self._plugins.keys())     # все включены по умолчанию
        enabled = self._config.get('plugins.enabled')
        if enabled is None:
            return set(self._plugins.keys())
        # Специальное значение: "*" — все
        if enabled == ['*'] or enabled == '*':
            return set(self._plugins.keys())
        # Список может содержать и disable-правила
        disabled = set(self._config.get('plugins.disabled', []) or [])
        return set(enabled) - disabled

    # ─────────── Информация ───────────

    def list(self) -> list[PluginInfo]:
        return list(self._plugins.values())

    def get(self, name: str) -> Optional[PluginInfo]:
        return self._plugins.get(name)

    def paths_for(self, kind: str) -> list[Path]:
        """
        Все пути указанного типа от включённых плагинов.
        kind ∈ {'commands','lib','email','langs','templates','static'}
        """
        result = []
        for info in self._plugins.values():
            if info.state not in (PluginState.LOADED, PluginState.ENABLED,
                                   PluginState.MIGRATED):
                continue
            p = getattr(info, f'{kind}_dir', None)
            if p:
                result.append(p)
        return result

    # ─────────── Миграции ───────────

    def run_migrations(self, driver: str, db, *,
                       auto_ok_only: bool = True,
                       homer_version: Optional[str] = None) -> dict:
        """
        Прогоняет:
          1) обычные миграции migrations/<driver>/ по порядку;
          2) upgrade-миграции migrations/upgrade_X/driver/
             для перехода с установленной версии на target.
        Обновляет homer_plugin_state.<version>.
        """
        from .migrations import MigrationRunner
        from .versions import VersionManager

        result = {
            'applied': [],
            'skipped': [],
            'errors': [],
            'upgraded': [],  # [(plugin, from, to)]
        }

        # Сначала топосортировка — плагины загружаются в правильном порядке
        try:
            from .deps import resolve
            ordered = resolve(
                {p.name: p for p in self._plugins.values()},
                homer_version=homer_version,
            )
        except Exception as e:
            result['errors'].append(('(global)', f"Зависимости: {e}"))
            # Всё равно пробуем применить по алфавиту
            ordered = sorted(self._plugins.values(), key=lambda p: p.name)

        vm = VersionManager(db, driver)

        for info in ordered:
            if auto_ok_only and not info.auto_migrate:
                result['skipped'].append(info.name)
                continue

            mig_dir = info.migrations_for(driver)
            has_upgrade = bool(vm.compute_upgrade_path(info, driver))

            if not mig_dir and not has_upgrade:
                continue

            # 1) обычные миграции
            if mig_dir:
                runner = MigrationRunner(info, driver, db)
                try:
                    applied = runner.up()
                    if applied:
                        result['applied'].extend(applied)
                except Exception as e:
                    result['errors'].append((info.name, str(e)))
                    info.state = PluginState.ERROR
                    info.error = f"migration: {e}"
                    continue

            # 2) upgrade-миграции
            try:
                steps = vm.compute_upgrade_path(info, driver)
                for step in steps:
                    def _apply(stmt, _db=db):
                        _db.execute(stmt)

                    n = vm.apply_upgrade(info, step, _apply)
                    result['upgraded'].append(
                        (info.name, step.from_version, step.to_version)
                    )
            except Exception as e:
                result['errors'].append((info.name, f"upgrade: {e}"))
                continue

            # 3) фиксируем версию
            try:
                vm.set_installed_version(info.name, info.version)
                info.state = PluginState.MIGRATED
            except Exception as e:
                result['errors'].append((info.name, f"version: {e}"))

        return result

    def uninstall_data(self, plugin_name: str, driver: str, db) -> bool:
        """
        Прогоняет uninstall.sql плагина (если существует).
        Вызывается только после подтверждения пользователя.
        """
        info = self._plugins.get(plugin_name)
        if not info:
            return False
        mig_dir = info.migrations_for(driver)
        if not mig_dir:
            return False
        uninstall_sql = mig_dir / 'uninstall.sql'
        if not uninstall_sql.exists():
            return False

        sql_text = uninstall_sql.read_text(encoding='utf-8')
        for stmt in _split_sql(sql_text, driver):
            db.execute(stmt)
        db.commit()
        _log.info(f"Плагин '{plugin_name}': uninstall.sql выполнен")
        return True


_manager: Optional[PluginManager] = None


def get_manager() -> PluginManager:
    """

    :rtype: object
    """
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager


# ─────────── SQL-утилиты ───────────

def _split_sql(text: str, driver: str) -> list[str]:
    """
    Грубое разбиение SQL на стейтменты по ';'.
    Для Oracle — учитываем '/' как разделитель блоков PL/SQL.
    """
    # Убираем комментарии -- и /* */
    lines = []
    in_block_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_block_comment:
            if '*/' in stripped:
                in_block_comment = False
                line = stripped.split('*/', 1)[1]
            else:
                continue
        if stripped.startswith('/*'):
            if '*/' not in stripped:
                in_block_comment = True
            continue
        if stripped.startswith('--'):
            continue
        lines.append(line)
    clean = '\n'.join(lines)

    if driver == 'oracle':
        # Oracle: разделители ';' для обычных и '/' для PL/SQL-блоков
        parts = []
        for chunk in clean.split('/'):
            for sub in chunk.split(';'):
                s = sub.strip()
                if s:
                    parts.append(s)
        return parts

    return [s.strip() for s in clean.split(';') if s.strip()]
