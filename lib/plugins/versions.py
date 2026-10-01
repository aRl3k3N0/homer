"""
Учёт установленных версий плагинов + миграции обновления.

Структура каталогов плагина:
    migrations/
        <driver>/
            001_init.sql
            002_add_x.sql
            uninstall.sql
        upgrade_1_0_1/           # миграции при апгрейде с <1.0.1
            <driver>/
                001_rename_col.sql
                ...
        upgrade_2_0_0/
            <driver>/
                ...

Порядок применения при старте:
    1) все "обычные" миграции из migrations/<driver>/, если ещё не применены
    2) все upgrade-миграции для версий в диапазоне
       (installed_version, target_version]

Обновление версии в homer_plugin_state после успеха.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .plugin import PluginInfo
from .deps import parse_version, _cmp_versions


DDL_STATE = {
    'sqlite': """
        CREATE TABLE IF NOT EXISTS homer_plugin_state (
            plugin_name       TEXT PRIMARY KEY,
            installed_version TEXT,
            installed_at      TEXT,
            updated_at        TEXT
        );
    """,
    'postgres': """
        CREATE TABLE IF NOT EXISTS homer_plugin_state (
            plugin_name       VARCHAR(255) PRIMARY KEY,
            installed_version VARCHAR(64),
            installed_at      TIMESTAMP,
            updated_at        TIMESTAMP
        );
    """,
    'oracle': """
        BEGIN
            EXECUTE IMMEDIATE '
                CREATE TABLE homer_plugin_state (
                    plugin_name       VARCHAR2(255) PRIMARY KEY,
                    installed_version VARCHAR2(64),
                    installed_at      TIMESTAMP,
                    updated_at        TIMESTAMP
                )';
        EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
        END;
    """,
    'mysql': """
        CREATE TABLE IF NOT EXISTS homer_plugin_state (
            plugin_name       VARCHAR(255) PRIMARY KEY,
            installed_version VARCHAR(64),
            installed_at      DATETIME,
            updated_at        DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
}

# Регулярка для нового формата: upgrade_1_0_0_to_1_1_0
_UP_RE = re.compile(r'^upgrade_(?P<from>.+?)_to_(?P<to>.+)$')
_DOWN_RE = re.compile(r'^downgrade_(?P<from>.+?)_to_(?P<to>.+)$')

def _parse_upgrade_dir(name: str) -> tuple[str, str] | None:
    m = _UP_RE.match(name)
    if not m:
        # Старый формат upgrade_X_Y_Z → считаем, что to = X.Y.Z
        m2 = re.match(r'^upgrade_(.+)$', name)
        if not m2:
            return None
        to = m2.group(1).replace('_', '.')
        return ('', to)
    return (m.group('from').replace('_', '.'),
            m.group('to').replace('_', '.'))


def _parse_downgrade_dir(name: str) -> tuple[str, str] | None:
    m = _DOWN_RE.match(name)
    if not m:
        m2 = re.match(r'^downgrade_(.+)$', name)
        if not m2:
            return None
        to = m2.group(1).replace('_', '.')
        return ('', to)
    return (m.group('from').replace('_', '.'),
            m.group('to').replace('_', '.'))


# В VersionManager.compute_upgrade_path:
def compute_upgrade_path(self, plugin, driver):
    installed = self.get_installed_version(plugin.name)
    target = plugin.version
    if installed is None or _cmp_versions(installed, target) >= 0:
        return []

    base = plugin.path / 'migrations'
    if not base.exists():
        return []

    steps = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        parsed = _parse_upgrade_dir(d.name)
        if not parsed:
            continue
        from_v, to_v = parsed
        if not to_v:
            continue
        # Если указан from_v — уважаем его, иначе применяем по диапазону
        if from_v and _cmp_versions(installed, from_v) < 0:
            continue
        if _cmp_versions(installed, to_v) < 0 and _cmp_versions(to_v, target) <= 0:
            driver_dir = d / driver
            if driver_dir.exists():
                steps.append(UpgradeStep(
                    from_version=from_v or installed,
                    to_version=to_v,
                    directory=driver_dir,
                    driver=driver,
                ))

    steps.sort(key=lambda s: parse_version(s.to_version))
    return steps


def compute_downgrade_path(self, plugin, driver, target_version):
    installed = self.get_installed_version(plugin.name) or plugin.version
    if _cmp_versions(installed, target_version) <= 0:
        return []

    base = plugin.path / 'migrations'
    if not base.exists():
        return []

    steps = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        parsed = _parse_downgrade_dir(d.name)
        if not parsed:
            continue
        from_v, to_v = parsed
        if not to_v:
            continue
        # Применяем downgrade, если его "from" <= installed и "to" >= target
        if _cmp_versions(from_v or installed, installed) > 0:
            continue
        if _cmp_versions(to_v, installed) <= 0 and _cmp_versions(to_v, target_version) >= 0:
            driver_dir = d / driver
            if driver_dir.exists():
                steps.append(DowngradeStep(
                    from_version=from_v or installed,
                    to_version=to_v,
                    directory=driver_dir,
                    driver=driver,
                ))

    # Сортировка: сначала большие версии
    steps.sort(key=lambda s: parse_version(s.to_version), reverse=True)
    return steps

@dataclass
class DowngradeStep:
    from_version: str
    to_version: str
    directory: Path
    driver: str


@dataclass
class UpgradeStep:
    from_version: str
    to_version: str
    directory: Path
    driver: str


class VersionManager:
    def __init__(self, db, driver: str):
        self.db = db
        self.driver = driver
        self._ensure_table()

    # ─────────── Состояние ───────────

    def _ensure_table(self):
        ddl = DDL_STATE.get(self.driver)
        if not ddl:
            raise RuntimeError(f"Нет DDL homer_plugin_state для {self.driver}")
        if self.driver == 'oracle':
            cur = self.db.cursor()
            try:
                cur.execute(ddl)
            finally:
                try: cur.close()
                except Exception: pass
        else:
            for stmt in [s.strip() for s in ddl.split(';') if s.strip()]:
                self.db.execute(stmt)
        self.db.commit()

    def get_installed_version(self, plugin_name: str) -> Optional[str]:
        row = self.db.fetchone(
            f"SELECT installed_version FROM homer_plugin_state "
            f"WHERE plugin_name = {self._ph(0)}",
            [plugin_name], dictionary=True,
        )
        if not row:
            return None
        return row['installed_version'] if isinstance(row, dict) else row[0]

    def set_installed_version(self, plugin_name: str, version: str,
                              is_new: bool = False):
        now = datetime.now()
        existing = self.get_installed_version(plugin_name)
        if existing is None:
            self.db.execute(
                f"INSERT INTO homer_plugin_state "
                f"(plugin_name, installed_version, installed_at, updated_at) "
                f"VALUES ({self._ph(0)}, {self._ph(1)}, {self._ph(2)}, "
                f"{self._ph(3)})",
                [plugin_name, version, now, now],
            )
        else:
            self.db.execute(
                f"UPDATE homer_plugin_state SET "
                f"  installed_version = {self._ph(0)}, "
                f"  updated_at = {self._ph(1)} "
                f"WHERE plugin_name = {self._ph(2)}",
                [version, now, plugin_name],
            )
        self.db.commit()

    # ─────────── Апгрейд ───────────

    def compute_upgrade_path(self, plugin: PluginInfo, driver: str
                             ) -> list[UpgradeStep]:
        """
        Находит все upgrade-каталоги, которые нужно применить
        для перехода с installed_version на plugin.version.
        """
        installed = self.get_installed_version(plugin.name)
        target = plugin.version
        steps: list[UpgradeStep] = []

        if installed is None:
            # Первая установка — upgrade-каталоги не применяем
            return []

        if _cmp_versions(installed, target) >= 0:
            return []

        base = plugin.path / 'migrations'
        if not base.exists():
            return []

        # Каталоги вида upgrade_<semver>
        candidates = []
        for d in base.iterdir():
            if not d.is_dir():
                continue
            m = re.match(r'^upgrade_(.+)$', d.name)
            if not m:
                continue
            ver = m.group(1).replace('_', '.')
            # 1_0_1 → 1.0.1
            ver = ver.strip('.')
            try:
                parse_version(ver)
            except Exception:
                continue
            candidates.append((ver, d))

        # Отбираем те, что: installed < upgrade_version <= target
        for ver, d in candidates:
            if _cmp_versions(installed, ver) < 0 and _cmp_versions(ver, target) <= 0:
                driver_dir = d / driver
                if driver_dir.exists():
                    steps.append(UpgradeStep(
                        from_version=installed, to_version=ver,
                        directory=driver_dir, driver=driver,
                    ))

        steps.sort(key=lambda s: parse_version(s.to_version))
        return steps

    def apply_upgrade(self, plugin: PluginInfo, step: UpgradeStep,
                      apply_sql) -> int:
        """
        Применяет все .sql в step.directory в порядке сортировки.
        apply_sql(stmt) — функция, выполняющая один стейтмент.
        Возвращает число применённых файлов.
        """
        from .migrations import _split_sql
        count = 0
        sqls = sorted(
            [f for f in step.directory.glob('*.sql')],
            key=lambda p: p.name,
        )
        for f in sqls:
            text = f.read_text(encoding='utf-8')
            for stmt in _split_sql(text, self.driver):
                apply_sql(stmt)
            count += 1
        self.db.commit()
        return count

    def compute_downgrade_path(self, plugin: PluginInfo, driver: str,
                               target_version: str) -> list[DowngradeStep]:
        """
        Находит downgrade-шаги от текущей установленной версии к target_version.

        Установлено = installed_version
        Целевое     = target_version

        Применяем downgrade_X_Y_Z в порядке убывания версий, где
            target_version <= version < installed_version
        """
        installed = self.get_installed_version(plugin.name) or plugin.version
        if _cmp_versions(installed, target_version) <= 0:
            return []

        base = plugin.path / 'migrations'
        if not base.exists():
            return []

        candidates = []
        for d in base.iterdir():
            if not d.is_dir():
                continue
            m = re.match(r'^downgrade_(.+)$', d.name)
            if not m:
                continue
            ver = m.group(1).replace('_', '.')
            try:
                parse_version(ver)
            except Exception:
                continue
            candidates.append((ver, d))

        # Отбираем: target_version <= v < installed_version
        selected = []
        for ver, d in candidates:
            if _cmp_versions(target_version, ver) <= 0 \
                and _cmp_versions(ver, installed) < 0:
                driver_dir = d / driver
                if driver_dir.exists():
                    selected.append((ver, driver_dir))

        # Порядок применения: сначала большее к меньшему
        selected.sort(key=lambda x: parse_version(x[0]), reverse=True)

        return [
            DowngradeStep(
                from_version=installed,
                to_version=ver,
                directory=ddir,
                driver=driver,
            )
            for ver, ddir in selected
        ]

    def apply_downgrade(self, plugin: PluginInfo, step: DowngradeStep,
                        apply_sql) -> int:
        from .migrations import _split_sql
        count = 0
        sqls = sorted(
            [f for f in step.directory.glob('*.sql')],
            key=lambda p: p.name,
        )
        for f in sqls:
            text = f.read_text(encoding='utf-8')
            for stmt in _split_sql(text, self.driver):
                apply_sql(stmt)
            count += 1
        self.db.commit()
        return count

    # ─────────── Хелперы ───────────

    def _ph(self, idx: int) -> str:
        style = getattr(self.db, '_placeholder_style', '%s')
        if style == ':name':
            return f':{idx + 1}'
        if style == '?':
            return '?'
        return '%s'
