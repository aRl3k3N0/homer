"""
plugin:scaffold-upgrade — генератор каталогов upgrade_X/ и downgrade_X/.

Что создаёт:
    plugins/<plugin>/migrations/upgrade_<from>_to_<to>/<driver>/001_xxx.sql
    plugins/<plugin>/migrations/downgrade_<from>_to_<to>/<driver>/001_xxx.sql

Аргументы:
    --name=<plugin>          (обязательно)
    --from=1.0.0             (опционально; если нет — берётся installed_version)
    --to=1.1.0               (опционально; если нет — берётся plugin.json.version)
    --drivers=sqlite,postgres,...   (по умолчанию все из migrations/)
    --what=add_column,...    (опционально: пресеты содержимого)
    --force                  (перезаписать существующие каталоги)

Пресеты --what (можно несколько через запятую):
    add_column       — ALTER TABLE ... ADD COLUMN + откат DROP COLUMN
    create_table     — CREATE TABLE + откат DROP TABLE
    add_index        — CREATE INDEX + откат DROP INDEX
    rename_column    — RENAME (для SQLite — через CREATE + INSERT SELECT)
    backfill         — UPDATE ... WHERE ... + откат (пустой комментарий)
    empty            — просто пустой файл с шапкой

Имена файлов:
    upgrade_<from>_to_<to>/<driver>/001_<what>.sql
    downgrade_<from>_to_<to>/<driver>/001_<what>.sql

Порядок применения (уже реализован в VersionManager):
    upgrade:   по возрастанию версий, из <from> в <to>
    downgrade: по убыванию версий, из <to> в <from>
"""
import re
from datetime import datetime
from pathlib import Path

from lib.console import console, Color

DESCRIPTION = "Сгенерировать каталоги upgrade/downgrade миграций"


# ─────────────────────────── Пресеты ───────────────────────────

PRESETS = ('add_column', 'create_table', 'add_index',
           'rename_column', 'backfill', 'empty')


def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9_]+', '_', s.lower()).strip('_') or 'change'


def _ver_dir(v: str) -> str:
    return v.replace('.', '_')


# ─────────────────────────── SQL-шаблоны ───────────────────────────

def _up_sql_add_column(plugin, driver, table, column, ctype):
    return f"""-- Upgrade: add column '{column}' to '{plugin}_{table}'
ALTER TABLE {plugin}_{table}
    ADD COLUMN {column} {ctype};
"""


def _down_sql_add_column(plugin, driver, table, column, ctype):
    if driver == 'sqlite':
        # SQLite поддерживает DROP COLUMN с 3.35
        return f"""-- Downgrade: drop column '{column}' from '{plugin}_{table}'
-- Требует SQLite 3.35+
ALTER TABLE {plugin}_{table}
    DROP COLUMN {column};
"""
    return f"""-- Downgrade: drop column '{column}' from '{plugin}_{table}'
ALTER TABLE {plugin}_{table}
    DROP COLUMN {column};
"""


def _up_sql_create_table(plugin, driver, table, ctype_pk, ctype_ts):
    return f"""-- Upgrade: create table '{plugin}_{table}'
CREATE TABLE IF NOT EXISTS {plugin}_{table} (
    id          {ctype_pk},
    created_at  {ctype_ts} NOT NULL,
    updated_at  {ctype_ts}
);
"""


def _down_sql_create_table(plugin, driver, table, *_):
    return f"""-- Downgrade: drop table '{plugin}_{table}'
DROP TABLE IF EXISTS {plugin}_{table};
"""


def _up_sql_add_index(plugin, driver, table, column, *_):
    return f"""-- Upgrade: index on '{plugin}_{table}.{column}'
CREATE INDEX IF NOT EXISTS {plugin}_{table}_{column}_idx
    ON {plugin}_{table} ({column});
"""


def _down_sql_add_index(plugin, driver, table, column, *_):
    return f"""-- Downgrade: drop index
DROP INDEX IF EXISTS {plugin}_{table}_{column}_idx;
"""


def _up_sql_rename_column(plugin, driver, table, old_col, new_col):
    if driver == 'sqlite':
        # SQLite: ALTER TABLE ... RENAME COLUMN с 3.25
        return f"""-- Upgrade: rename column '{old_col}' → '{new_col}' in '{plugin}_{table}'
ALTER TABLE {plugin}_{table}
    RENAME COLUMN {old_col} TO {new_col};
"""
    if driver == 'oracle':
        return f"""-- Upgrade: rename column '{old_col}' → '{new_col}' in '{plugin}_{table}'
ALTER TABLE {plugin}_{table}
    RENAME COLUMN {old_col} TO {new_col};
"""
    if driver == 'mssql':
        return f"""-- Upgrade: rename column '{old_col}' → '{new_col}' in '{plugin}_{table}'
EXEC sp_rename '{plugin}_{table}.{old_col}', '{new_col}', 'COLUMN';
"""
    return f"""-- Upgrade: rename column '{old_col}' → '{new_col}' in '{plugin}_{table}'
ALTER TABLE {plugin}_{table}
    RENAME COLUMN {old_col} TO {new_col};
"""


def _down_sql_rename_column(plugin, driver, table, old_col, new_col):
    return _up_sql_rename_column(plugin, driver, table, new_col, old_col)


def _up_sql_backfill(plugin, driver, table, column, *_):
    return f"""-- Upgrade: backfill column '{column}' in '{plugin}_{table}'
-- Заполните данные. Пример:
-- UPDATE {plugin}_{table}
--     SET {column} = <value>
--     WHERE {column} IS NULL;
"""


def _down_sql_backfill(plugin, driver, table, column, *_):
    return f"""-- Downgrade: обратная операция для backfill '{column}'
-- Пример:
-- UPDATE {plugin}_{table}
--     SET {column} = NULL;
"""


def _up_sql_empty(plugin, driver, table='', column='', *_):
    return f"""-- Upgrade: {plugin} ({driver})
-- Свой SQL здесь.
"""


def _down_sql_empty(plugin, driver, *_):
    return f"""-- Downgrade: {plugin} ({driver})
-- Обратные действия для апгрейда.
"""


UP_SQL = {
    'add_column':    _up_sql_add_column,
    'create_table':  _up_sql_create_table,
    'add_index':     _up_sql_add_index,
    'rename_column': _up_sql_rename_column,
    'backfill':      _up_sql_backfill,
    'empty':         _up_sql_empty,
}

DOWN_SQL = {
    'add_column':    _down_sql_add_column,
    'create_table':  _down_sql_create_table,
    'add_index':     _down_sql_add_index,
    'rename_column': _down_sql_rename_column,
    'backfill':      _down_sql_backfill,
    'empty':         _down_sql_empty,
}


# ─────────────────────────── Типы ───────────────────────────

def _pk_type(driver):
    return {
        'sqlite':   'INTEGER PRIMARY KEY AUTOINCREMENT',
        'postgres': 'SERIAL PRIMARY KEY',
        'mysql':    'INT AUTO_INCREMENT PRIMARY KEY',
        'oracle':   'NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY',
        'mssql':    'INT IDENTITY(1,1) PRIMARY KEY',
    }.get(driver, 'INTEGER PRIMARY KEY')


def _ts_type(driver):
    return {
        'sqlite':   'TEXT',
        'postgres': 'TIMESTAMP',
        'mysql':    'DATETIME',
        'oracle':   'TIMESTAMP',
        'mssql':    'DATETIME2',
    }.get(driver, 'TIMESTAMP')


# ─────────────────────────── Ядро ───────────────────────────

def _discover_drivers(plugin_dir: Path) -> list[str]:
    """Какие драйверы уже используются в плагине."""
    mig = plugin_dir / 'migrations'
    if not mig.exists():
        return ['sqlite']
    return sorted([
        d.name for d in mig.iterdir()
        if d.is_dir() and not d.name.startswith(('upgrade_', 'downgrade_'))
    ]) or ['sqlite']


def _existing_upgrade_dirs(plugin_dir: Path) -> set[str]:
    mig = plugin_dir / 'migrations'
    if not mig.exists():
        return set()
    return {
        d.name for d in mig.iterdir()
        if d.is_dir() and d.name.startswith('upgrade_')
    }


def _existing_downgrade_dirs(plugin_dir: Path) -> set[str]:
    mig = plugin_dir / 'migrations'
    if not mig.exists():
        return set()
    return {
        d.name for d in mig.iterdir()
        if d.is_dir() and d.name.startswith('downgrade_')
    }


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def execute(context):
    args = context['args']
    root = Path(context['root_dir'])
    cfg = context['config']

    plugin_name = args.get('name')
    if not plugin_name:
        console.error(
            "Использование: homer plugin:scaffold-upgrade --name=<plugin> "
            "[--from=1.0.0] [--to=1.1.0] [--drivers=sqlite,postgres] "
            "[--what=add_column] [--force]"
        )
        return 1

    plugin_dir = root / 'plugins' / plugin_name
    if not plugin_dir.exists():
        console.error(f"Плагин '{plugin_name}' не найден")
        return 1

    # ─── from/to ───
    from_version = args.get('from')
    to_version = args.get('to')

    # Из БД, если не задано
    if not from_version:
        try:
            from lib.db import connect
            from lib.plugins.versions import VersionManager
            sched_cfg = cfg.get('scheduler', {}) or {}
            driver = sched_cfg.get('storage', 'sqlite')
            conn_cfg = sched_cfg.get(driver) or cfg.get(f'databases.{driver}')
            if driver == 'sqlite':
                if not conn_cfg:
                    conn_cfg = {'path': 'var/scheduler.db'}
                elif 'path' not in conn_cfg:
                    conn_cfg = dict(conn_cfg, path='var/scheduler.db')
            db = connect(driver, conn_cfg)
            try:
                vm = VersionManager(db, driver)
                from_version = vm.get_installed_version(plugin_name)
            finally:
                db.close()
        except Exception:
            pass

    # Из plugin.json
    if not to_version:
        try:
            from lib.plugins.plugin import PluginInfo
            info = PluginInfo.from_dir(plugin_dir)
            to_version = info.version
        except Exception:
            pass

    if not from_version or not to_version:
        console.error(
            "Не удалось определить версии. Укажите --from=X --to=Y"
        )
        return 1

    if not re.match(r'^\d+\.\d+\.\d+', from_version) or \
       not re.match(r'^\d+\.\d+\.\d+', to_version):
        console.error("Версии должны быть в формате X.Y.Z")
        return 1

    if from_version == to_version:
        console.error("Версии совпадают — нечего генерировать")
        return 1

    # ─── Драйверы ───
    drivers_arg = args.get('drivers')
    if drivers_arg:
        drivers = [d.strip() for d in str(drivers_arg).split(',') if d.strip()]
    else:
        drivers = _discover_drivers(plugin_dir)

    # ─── Пресеты ───
    what_arg = args.get('what') or 'empty'
    what_list = [w.strip() for w in str(what_arg).split(',') if w.strip()]
    for w in what_list:
        if w not in PRESETS:
            console.error(f"Неизвестный пресет '{w}'. "
                          f"Доступные: {', '.join(PRESETS)}")
            return 1

    # Параметры для пресетов
    table = args.get('table') or 'data'
    column = args.get('column') or 'new_col'
    old_col = args.get('old') or 'old_col'
    new_col = args.get('new') or 'new_col'
    ctype = args.get('type') or 'TEXT'

    force = bool(args.get('force', False))

    # ─── Имена каталогов ───
    # upgrade_1_0_0_to_1_1_0 — явное указание пути
    up_dirname = f"upgrade_{_ver_dir(from_version)}_to_{_ver_dir(to_version)}"
    down_dirname = f"downgrade_{_ver_dir(to_version)}_to_{_ver_dir(from_version)}"

    up_root = plugin_dir / 'migrations' / up_dirname
    down_root = plugin_dir / 'migrations' / down_dirname

    # Проверим существование
    if up_root.exists() and not force:
        console.warning(f"Каталог существует: {up_root.relative_to(root)}")
        console.comment("Используйте --force для перезаписи")
    if down_root.exists() and not force:
        console.warning(f"Каталог существует: {down_root.relative_to(root)}")

    # ─── Генерация ───
    console.banner("plugin:scaffold-upgrade",
                   f"{plugin_name}: {from_version} → {to_version}")
    console.key_value('Драйверы', ', '.join(drivers))
    console.key_value('Пресеты', ', '.join(what_list))

    created_files = []
    for driver in drivers:
        pk = _pk_type(driver)
        ts = _ts_type(driver)

        for idx, what in enumerate(what_list, start=1):
            up_file = up_root / driver / f"{idx:03d}_{_slug(what)}.sql"
            down_file = down_root / driver / f"{idx:03d}_{_slug(what)}.sql"

            if up_file.exists() and not force:
                console.comment(f"  пропуск (есть): {up_file.name}")
            else:
                sql = UP_SQL[what](plugin_name, driver, table, column,
                                    ctype, pk, ts)
                header = (f"-- Plugin:    {plugin_name}\n"
                          f"-- Driver:    {driver}\n"
                          f"-- Upgrade:   {from_version} → {to_version}\n"
                          f"-- Created:   {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                          f"-- Preset:    {what}\n\n")
                _write(up_file, header + sql)
                created_files.append(up_file)

            if down_file.exists() and not force:
                console.comment(f"  пропуск (есть): {down_file.name}")
            else:
                # Обратный пресет для rename
                if what == 'rename_column':
                    sql = DOWN_SQL[what](plugin_name, driver, table,
                                          old_col, new_col, ctype, pk, ts)
                else:
                    sql = DOWN_SQL[what](plugin_name, driver, table,
                                          column, ctype, pk, ts)
                header = (f"-- Plugin:    {plugin_name}\n"
                          f"-- Driver:    {driver}\n"
                          f"-- Downgrade: {to_version} → {from_version}\n"
                          f"-- Created:   {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                          f"-- Preset:    {what}\n\n")
                _write(down_file, header + sql)
                created_files.append(down_file)

    console.newline()
    console.success(f"Создано файлов: {len(created_files)}")

    for f in created_files:
        console.print(f"  {console.colored('+', Color.BRIGHT_GREEN)} "
                      f"{f.relative_to(root)}")

    console.newline()
    console.section("Дальнейшие шаги")
    console.list_item('1. Отредактировать', f'SQL в {up_root.relative_to(root)}/')
    console.list_item('2. Проверить', f'homer plugin:check --name={plugin_name}')
    console.list_item('3. Обновить version',
                      f'в plugins/{plugin_name}/plugin.json → {to_version}')
    console.list_item('4. Применить', f'homer plugin:upgrade --name={plugin_name} --apply')
    console.list_item('5. Откатить', f'homer plugin:downgrade --name={plugin_name} '
                                     f'--to={from_version} --apply')
    console.list_item('6. Зафиксировать', 'homer lock:update')
    return 0
