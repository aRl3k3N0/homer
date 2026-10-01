"""
Команды управления плагинами: list, migrate, enable, disable, uninstall.
"""
from pathlib import Path

from lib.console import console, Color
from lib.plugins.deps import parse_version

DESCRIPTIONS = {
    'list':      "Список плагинов и их состояние",
    'migrate':   "Применить миграции плагинов",
    'enable':    "Включить плагин",
    'disable':   "Выключить плагин",
    'uninstall': "Удалить данные плагина (только uninstall.sql)",
    'info':      "Информация о плагине",
    'rollback':  "Откатить все миграции плагина (выполнить uninstall.sql)",
    'check':     "Валидация структуры плагинов без загрузки",
    'upgrade':   "Применить upgrade-миграции (обновление версий)",
    'reload':    "Перезагрузить плагин(ы) без остановки Homer",
}


# ─────────── Helpers ───────────

def _get_manager_and_config(context):
    from lib.plugins import get_manager
    from lib.db import connect

    mgr = get_manager()
    cfg = context['config']
    root = Path(context['root_dir'])

    # Если ещё не сканировали — сделаем
    if not mgr.list():
        mgr.discover(root / 'plugins', cfg)

    # Подключение к БД
    sched_cfg = cfg.get('scheduler', {}) or {}
    driver = sched_cfg.get('storage', 'sqlite')
    conn_cfg = sched_cfg.get(driver) or cfg.get(f'databases.{driver}')
    if driver == 'sqlite':
        if not conn_cfg:
            conn_cfg = {'path': 'var/scheduler.db'}
        elif 'path' not in conn_cfg:
            conn_cfg = dict(conn_cfg, path='var/scheduler.db')
    db = connect(driver, conn_cfg)

    return mgr, cfg, db, driver


# ─────────── Команды ───────────

def list_plugins(context):
    mgr, cfg, db, driver = _get_manager_and_config(context)
    try:
        plugins = mgr.list()
        if not plugins:
            console.warning("Плагинов нет")
            return 0

        # Загружаем, чтобы получить состояния
        mgr.load_all(context)

        rows = []
        for p in plugins:
            state_color = {
                'enabled': Color.BRIGHT_GREEN,
                'disabled': Color.BRIGHT_BLACK,
                'error': Color.BRIGHT_RED,
                'migrated': Color.BRIGHT_CYAN,
                'loaded': Color.BRIGHT_YELLOW,
                'discovered': Color.WHITE,
            }.get(p.state, Color.WHITE)

            rows.append([
                p.name,
                p.version,
                console.colored(p.state, state_color),
                p.description[:40],
                'да' if p.auto_migrate else 'нет',
            ])
        console.table(
            headers=['Плагин', 'Версия', 'Состояние', 'Описание', 'Auto-migrate'],
            rows=rows,
            align=['l', 'l', 'c', 'l', 'c'],
        )
    finally:
        db.close()
    return 0


def info(context):
    mgr, cfg, db, driver = _get_manager_and_config(context)
    try:
        name = context['args'].get('name') or \
               (context['args'].get('_positional') or [None])[0]
        if not name:
            console.error("Укажите --name=<plugin>")
            return 1
        p = mgr.get(name)
        if not p:
            console.error(f"Плагин '{name}' не найден")
            return 1

        mgr.load_all(context)

        console.banner(f"Плагин: {p.name}", f"v{p.version}")
        console.key_value('Описание', p.description)
        console.key_value('Автор', p.author or '—')
        console.key_value('Дом. страница', p.homepage or '—')
        console.key_value('Требует Homer', p.requires_homer)
        console.key_value('Зависимости', ', '.join(p.requires) or '—')
        console.key_value('Состояние', p.state)
        console.key_value('Путь', str(p.path))
        if p.error:
            console.error(f"Ошибка: {p.error}")

        # Миграции
        from lib.plugins.migrations import MigrationRunner
        mig_dir = p.migrations_for(driver)
        if mig_dir:
            runner = MigrationRunner(p, driver, db)
            status = runner.status()
            if status:
                console.section(f"Миграции ({driver})")
                rows = [
                    [
                        m['name'],
                        console.colored('✔', Color.BRIGHT_GREEN) if m['applied']
                        else console.colored('·', Color.BRIGHT_BLACK),
                    ]
                    for m in status
                ]
                console.table(headers=['Файл', 'Применена'], rows=rows,
                              align=['l', 'c'])
    finally:
        db.close()
    return 0


def migrate(context):
    mgr, cfg, db, driver = _get_manager_and_config(context)
    try:
        name = context['args'].get('name')
        mgr.discover(Path(context['root_dir']) / 'plugins', cfg)
        mgr.load_all(context)

        # Применяем ко всем или к одному
        if name:
            p = mgr.get(name)
            if not p:
                console.error(f"Плагин '{name}' не найден")
                return 1
            from lib.plugins.migrations import MigrationRunner
            mig_dir = p.migrations_for(driver)
            if not mig_dir:
                console.warning(f"У плагина '{name}' нет миграций для {driver}")
                return 0
            runner = MigrationRunner(p, driver, db)
            applied = runner.up()
            if applied:
                for a in applied:
                    console.success(f"Применена: {a}")
            else:
                console.comment("Нет новых миграций")
        else:
            result = mgr.run_migrations(driver, db)
            for a in result['applied']:
                console.success(f"Применена: {a}")
            for s in result['skipped']:
                console.comment(f"Пропущен (auto_migrate=false): {s}")
            for name_, err in result['errors']:
                console.error(f"{name_}: {err}")

        return 0
    finally:
        db.close()


def enable(context):
    return _toggle(context, True)


def disable(context):
    return _toggle(context, False)


def _toggle(context, enabled: bool):
    from lib.config import Config

    name = context['args'].get('name')
    if not name:
        console.error("Укажите --name=<plugin>")
        return 1

    root = Path(context['root_dir'])
    cfg_path = root / 'config.yml'

    # Меняем config.yml через Config API
    cfg = context['config']
    plugins_cfg = cfg.get('plugins', {}) or {}
    enabled_list = set(plugins_cfg.get('enabled', []) or [])

    if enabled:
        enabled_list.add(name)
    else:
        enabled_list.discard(name)

    plugins_cfg['enabled'] = sorted(enabled_list)

    # Записываем
    import yaml
    data = cfg.all()
    data['plugins'] = plugins_cfg
    cfg_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding='utf-8',
    )

    state = 'включён' if enabled else 'выключен'
    console.success(f"Плагин '{name}' {state} (изменён config.yml)")
    console.comment("Перезапустите Homer, чтобы изменения вступили в силу")
    return 0


def uninstall(context):
    """Прогоняет uninstall.sql плагина — только по подтверждению."""
    mgr, cfg, db, driver = _get_manager_and_config(context)
    try:
        name = context['args'].get('name')
        if not name:
            console.error("Укажите --name=<plugin>")
            return 1

        p = mgr.get(name)
        if not p:
            console.error(f"Плагин '{name}' не найден")
            return 1

        mig_dir = p.migrations_for(driver)
        if not mig_dir:
            console.error(f"У плагина '{name}' нет миграций для {driver}")
            return 1

        uninstall_sql = mig_dir / 'uninstall.sql'
        if not uninstall_sql.exists():
            console.error(f"У плагина '{name}' нет uninstall.sql")
            return 1

        # Показываем содержимое
        console.section(f"uninstall.sql плагина {name}")
        print(uninstall_sql.read_text(encoding='utf-8'))

        # Двойное подтверждение
        console.warning(
            f"Это действие УДАЛИТ данные плагина '{name}'. "
            f"Отменить будет нельзя."
        )
        if not console.confirm("Продолжить?", default=False):
            console.comment("Отменено")
            return 0
        code = console.ask(f"Введите {console.bold(name)} для подтверждения")
        if code != name:
            console.error("Отменено (код не совпал)")
            return 1

        from lib.plugins.migrations import MigrationRunner
        runner = MigrationRunner(p, driver, db)
        if runner.down_all():
            console.success(f"Данные плагина '{name}' удалены")
        else:
            console.error("uninstall.sql не выполнен")
            return 1

        return 0
    finally:
        db.close()


def rollback(context):
    """То же, что uninstall, но под другим именем."""
    return uninstall(context)

# lib/commands/plugin.py — добавьте функцию

def check(context):
    """
    Валидация структуры плагинов без загрузки.
    """
    from pathlib import Path
    from lib.plugins.validator import (
        PluginValidator, render_reports,
    )

    root = Path(context['root_dir'])
    plugins_dir = root / 'plugins'

    if not plugins_dir.exists():
        console.warning("Каталог plugins/ не найден")
        return 0

    homer_version = context['config'].get('app.version', '1.0.0')
    strict = bool(context['args'].get('strict', False))
    name = context['args'].get('name')

    validator = PluginValidator(plugins_dir, homer_version=homer_version)

    if name:
        plugin_dir = plugins_dir / name
        if not plugin_dir.exists():
            console.error(f"Плагин '{name}' не найден")
            return 1
        reports = [validator.check_one(plugin_dir)]
    else:
        reports = validator.check_all()

    console.banner("plugin:check", "валидация плагинов")

    n_errors, n_warnings = render_reports(reports, console)

    console.line()
    summary = (f"Ошибок: {n_errors}, предупреждений: {n_warnings}, "
               f"проверено плагинов: {len(reports)}")
    if n_errors:
        console.error(summary)
        return 1
    if n_warnings and strict:
        console.warning(summary + " (--strict: warnings → failure)")
        return 1
    console.success(summary)
    return 0

def upgrade(context):
    """
    Показать/применить upgrade-миграции для плагинов.
    По умолчанию — dry-run; применение — с --apply.
    """
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.versions import VersionManager
    from lib.db import connect

    root = Path(context['root_dir'])
    cfg = context['config']

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)

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
        apply_ = bool(context['args'].get('apply'))
        name = context['args'].get('name')

        plugins = [mgr.get(name)] if name else mgr.list()
        if not plugins or plugins == [None]:
            console.error("Плагинов нет")
            return 1

        rows = []
        plans: list[tuple] = []
        for p in plugins:
            installed = vm.get_installed_version(p.name) or '—'
            target = p.version
            steps = vm.compute_upgrade_path(p, driver)
            status = (
                'актуален' if installed == target
                else ('новая установка' if installed == '—'
                      else f"обновить {installed} → {target}")
            )
            rows.append([
                p.name,
                installed,
                target,
                status,
                str(len(steps)) if steps else '0',
            ])
            plans.append((p, steps))

        console.table(
            headers=['Плагин', 'Установлено', 'В plugin.json',
                     'Статус', 'Upgrade-шагов'],
            rows=rows,
            align=['l', 'l', 'l', 'l', 'c'],
        )

        if not apply_:
            console.comment("Dry-run. Для применения: plugin:upgrade --apply")
            return 0

        for p, steps in plans:
            if not steps:
                continue
            console.section(f"{p.name}: {len(steps)} шаг(ов)")
            for step in steps:
                console.info(f"{step.from_version} → {step.to_version} "
                             f"({step.directory})")
                def _apply(stmt):
                    db.execute(stmt)
                n = vm.apply_upgrade(p, step, _apply)
                console.success(f"применено файлов: {n}")

            vm.set_installed_version(p.name, p.version)
            console.success(f"{p.name}: версия обновлена на {p.version}")
        return 0
    finally:
        db.close()

def reload(context):
    """
    Перезагрузить плагин(ы) без остановки Homer.
    Работает только в том процессе, где запущено ядро.
    """
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.reload import PluginReloader

    mgr = get_manager()
    root = Path(context['root_dir'])

    if not mgr.list():
        mgr.discover(root / 'plugins', context['config'])
        mgr.load_all(context)

    reloader = PluginReloader(
        mgr, root_dir=root,
        config=context['config'],
        homer_context={
            'config': context['config'],
            'logger': context['logger'],
            'root_dir': root,
        },
    )

    name = context['args'].get('name')
    all_ = bool(context['args'].get('all', False))

    if all_:
        results = reloader.reload_all()
        failed = [n for n, ok in results.items() if not ok]
        for n, ok in results.items():
            if ok:
                console.success(f"Перезагружен: {n}")
            else:
                console.error(f"Ошибка перезагрузки: {n}")
        return 1 if failed else 0

    if not name:
        console.error("Укажите --name=<plugin> или --all")
        return 1

    ok = reloader.reload(name)
    if ok:
        console.success(f"Плагин '{name}' перезагружен")
        return 0
    console.error(f"Не удалось перезагрузить '{name}'")
    return 1

def install(context):
    from pathlib import Path
    from lib.plugins.installer import PluginInstaller, InstallError
    from lib.plugins.registry import Registry, RegistryError

    args = context['args']
    source = args.get('source') or args.get('_positional', [None])[0]
    from_registry = args.get('from_registry') or args.get('from-registry')

    root = Path(context['root_dir'])
    cfg = context['config']
    installer = PluginInstaller(root, config=cfg)

    # ─── Из реестра ───
    if from_registry:
        reg = _get_registry(context)
        if reg is None:
            return 1
        try:
            p = reg.get_plugin(from_registry)
        except Exception as e:
            console.error(str(e))
            return 1
        if not p:
            console.error(f"Плагин '{from_registry}' не найден в реестре")
            return 1

        version = args.get('version')
        if version:
            v = p.find(version)
            if not v:
                console.error(f"Версия {version} не найдена")
                return 1
        else:
            v = p.latest()
            if not v:
                console.error(f"У плагина '{from_registry}' нет версий")
                return 1

        source = v.url

        # Проверим checksum после скачивания
        console.section(f"Установка {p.name} v{v.version} из реестра")
        console.key_value('URL', source)
        if v.checksum:
            console.key_value('Ожидаемый checksum', v.checksum[:20] + '...')
        if v.signature_key_id:
            console.key_value('Подписан ключом', v.signature_key_id)

        try:
            result = installer.install(
                source,
                force=bool(args.get('force', False)),
                enable=(args.get('enable', True) is not False),
                migrate=(args.get('migrate', True) is not False),
                expected_name=p.name,
                expected_checksum=v.checksum,
                verify=bool(args.get('verify', True))
                       and bool(v.signature_key_id),
            )
        except InstallError as e:
            console.error(str(e))
            return 1

        console.success(f"Установлен {result.name} v{result.version}")
        return 0

    # ─── Обычная установка ───
    if not source:
        console.error(
            "Использование:\n"
            "  homer plugin:install <path|url|git+url>\n"
            "  homer plugin:install --from-registry=<name> [--version=X]"
        )
        return 1

    verify = args.get('verify', False) is not False
    allow_unsigned = bool(args.get('allow_unsigned', False))
    expected_checksum = args.get('checksum')

    try:
        result = installer.install(
            source,
            force=bool(args.get('force', False)),
            enable=(args.get('enable', True) is not False),
            migrate=(args.get('migrate', True) is not False),
            verify=verify,
            allow_unsigned=allow_unsigned,
            expected_checksum=expected_checksum,
        )
    except InstallError as e:
        console.error(str(e))
        return 1

    console.success(f"Установлен {result.name} v{result.version}")
    return 0


def remove(context):
    """Удалить плагин (с опциональным удалением данных)."""
    from pathlib import Path
    from lib.plugins.installer import PluginInstaller, InstallError

    args = context['args']
    name = args.get('name')
    if not name:
        console.error("Укажите --name=<plugin>")
        return 1

    purge = bool(args.get('purge', False))

    root = Path(context['root_dir'])
    installer = PluginInstaller(root, config=context['config'])

    # Подключение к БД, если purge
    db = None
    driver = None
    if purge:
        from lib.db import connect
        sched_cfg = (context['config'].get('scheduler', {}) or {})
        driver = sched_cfg.get('storage', 'sqlite')
        conn_cfg = (sched_cfg.get(driver)
                    or context['config'].get(f'databases.{driver}'))
        if driver == 'sqlite':
            if not conn_cfg:
                conn_cfg = {'path': 'var/scheduler.db'}
            elif 'path' not in conn_cfg:
                conn_cfg = dict(conn_cfg, path='var/scheduler.db')
        db = connect(driver, conn_cfg)

        console.warning(
            f"Будут УДАЛЕНЫ данные плагина '{name}' (uninstall.sql)."
        )
        if not console.confirm("Продолжить?", default=False):
            console.comment("Отменено")
            db.close()
            return 0
        typed = console.ask(f"Введите {console.bold(name)} для подтверждения")
        if typed != name:
            console.error("Отменено")
            db.close()
            return 1

    try:
        installer.uninstall(name, purge_data=purge, driver=driver, db=db)
        console.success(f"Плагин '{name}' удалён")
        return 0
    except InstallError as e:
        console.error(str(e))
        return 1
    finally:
        if db:
            db.close()

def downgrade(context):
    """
    Откатить плагин к указанной версии.
    Требует --to=<version> и подтверждения.
    """
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.versions import VersionManager
    from lib.db import connect

    args = context['args']
    name = args.get('name')
    target = args.get('to')
    if not name or not target:
        console.error("Использование: homer plugin:downgrade --name=X --to=1.5.0")
        return 1

    root = Path(context['root_dir'])
    cfg = context['config']

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)
    p = mgr.get(name)
    if not p:
        console.error(f"Плагин '{name}' не найден")
        return 1

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
        installed = vm.get_installed_version(name) or '—'
        steps = vm.compute_downgrade_path(p, driver, target)

        console.section(f"Downgrade {name}")
        console.key_value('Установлено', installed)
        console.key_value('Цель', target)
        console.key_value('Шагов', str(len(steps)))

        if not steps:
            console.warning("Нет downgrade-миграций для этого перехода")
            return 0

        for s in steps:
            console.list_item(f"{s.from_version} → {s.to_version}",
                              str(s.directory.relative_to(root)))

        if not args.get('apply'):
            console.comment("Dry-run. Применить: --apply")
            return 0

        console.warning("Downgrade может привести к потере данных.")
        if not console.confirm("Продолжить?", default=False):
            return 0

        for s in steps:
            def _apply(stmt):
                db.execute(stmt)
            n = vm.apply_downgrade(p, s, _apply)
            console.success(f"{s.from_version} → {s.to_version}: "
                            f"{n} файлов")
            vm.set_installed_version(name, s.to_version)

        console.success(f"Downgrade завершён: {name} → {target}")
        return 0
    finally:
        db.close()

def lock_update(context):
    """Зафиксировать текущее состояние плагинов в plugins.lock."""
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.lock import PluginsLock
    from lib.db import connect

    root = Path(context['root_dir'])
    cfg = context['config']

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)
    mgr.load_all(context)

    plugins = mgr.list()
    if not plugins:
        console.warning("Плагинов нет")
        return 0

    # Обновляем применение миграций из БД
    sched_cfg = cfg.get('scheduler', {}) or {}
    driver = sched_cfg.get('storage', 'sqlite')
    conn_cfg = sched_cfg.get(driver) or cfg.get(f'databases.{driver}')
    if driver == 'sqlite':
        if not conn_cfg:
            conn_cfg = {'path': 'var/scheduler.db'}
        elif 'path' not in conn_cfg:
            conn_cfg = dict(conn_cfg, path='var/scheduler.db')

    lock = PluginsLock(root)
    lock.save(
        homer_version=cfg.get('app.version', '1.0.0'),
        plugins=plugins,
    )

    try:
        db = connect(driver, conn_cfg)
        try:
            lock.update_from_db(driver, db)
        finally:
            db.close()
    except Exception as e:
        console.warning(f"Не удалось прочитать applied_at: {e}")

    console.success(f"plugins.lock обновлён: {lock.path.name}")
    console.key_value('Плагинов', len(plugins))
    return 0


def lock_check(context):
    """Сверить lock с текущим состоянием."""
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.lock import PluginsLock

    root = Path(context['root_dir'])
    cfg = context['config']

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)

    lock = PluginsLock(root)
    if not lock.exists():
        console.warning("plugins.lock не найден")
        return 0

    lock.load()
    drivers = list({
        cfg.get('scheduler.storage', 'sqlite'),
    })
    issues = lock.verify(mgr.list(), drivers)

    if not issues:
        console.success("Lock совпадает с текущим состоянием")
        return 0

    from lib.console import Color
    severity_color = {
        'version':          Color.BRIGHT_YELLOW,
        'files_changed':    Color.BRIGHT_RED,
        'migration_changed': Color.BRIGHT_RED,
        'migration_added':  Color.BRIGHT_YELLOW,
        'migration_removed': Color.BRIGHT_YELLOW,
        'missing':          Color.BRIGHT_RED,
        'extra':            Color.BRIGHT_YELLOW,
    }

    console.section(f"Расхождения в lock ({len(issues)})")
    for i in issues:
        color = severity_color.get(i['type'], Color.WHITE)
        console.print(console.colored(f"  [{i['type']}] {i['message']}",
                                       color))

    console.newline()
    if any(i['type'] in ('files_changed', 'migration_changed',
                          'missing') for i in issues):
        console.error("Есть критические расхождения")
        return 1
    console.warning("Есть предупреждения")
    return 0

def audit(context):
    """
    Полный отчёт по плагинам:
        - версии (установленная vs. plugin.json)
        - состояние
        - зависимости
        - миграции (применены/нет/пропущены)
        - даты (installed_at, updated_at)
        - checksum vs lock
        - предупреждения валидатора
    """
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.lock import PluginsLock
    from lib.plugins.validator import PluginValidator
    from lib.plugins.versions import VersionManager
    from lib.db import connect

    root = Path(context['root_dir'])
    cfg = context['config']

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)
    mgr.load_all(context)

    plugins = mgr.list()
    if not plugins:
        console.warning("Плагинов нет")
        return 0

    # БД
    sched_cfg = cfg.get('scheduler', {}) or {}
    driver = sched_cfg.get('storage', 'sqlite')
    conn_cfg = sched_cfg.get(driver) or cfg.get(f'databases.{driver}')
    if driver == 'sqlite':
        if not conn_cfg:
            conn_cfg = {'path': 'var/scheduler.db'}
        elif 'path' not in conn_cfg:
            conn_cfg = dict(conn_cfg, path='var/scheduler.db')

    db = None
    try:
        db = connect(driver, conn_cfg)
    except Exception as e:
        console.warning(f"БД недоступна ({e}); пропускаем миграции/версии")

    try:
        vm = VersionManager(db, driver) if db else None
        lock = PluginsLock(root)
        if lock.exists():
            lock.load()

        # ─── Общая таблица ───
        console.banner("plugin:audit", "Аудит установленных плагинов")

        rows = []
        for p in plugins:
            installed = (vm.get_installed_version(p.name) or '—') if vm else '—'
            match = ('✔' if installed == p.version
                     else ('new' if installed == '—' else '≠'))

            requires = ', '.join(p.requires or []) or '—'
            rows.append([
                p.name,
                p.version,
                installed,
                console.colored(match,
                                 Color.BRIGHT_GREEN if match == '✔'
                                 else (Color.BRIGHT_YELLOW
                                       if match == 'new'
                                       else Color.BRIGHT_RED)),
                p.state,
                requires,
            ])
        console.table(
            headers=['Плагин', 'В plugin.json', 'Установлено',
                     '= ', 'Состояние', 'Зависимости'],
            rows=rows,
            align=['l', 'l', 'l', 'c', 'c', 'l'],
        )

        # ─── Детали по каждому плагину ───
        for p in plugins:
            console.section(f"{p.name} v{p.version}")

            console.key_value('Путь', str(p.path.relative_to(root)))
            console.key_value('Состояние', p.state)
            if p.description:
                console.key_value('Описание', p.description)
            if p.author:
                console.key_value('Автор', p.author)
            if p.requires_homer:
                console.key_value('Требует Homer', p.requires_homer)

            # Даты из БД
            if vm:
                installed = vm.get_installed_version(p.name)
                if installed:
                    console.key_value('Установлен', installed)

            # Валидатор (без вывода всех issues, только counts)
            try:
                v = PluginValidator(root / 'plugins',
                                    homer_version=cfg.get('app.version', '1.0.0'))
                rep = v.check_one(p.path)
                errs = sum(1 for i in rep.issues if i.severity == 'error')
                warns = sum(1 for i in rep.issues if i.severity == 'warning')
                infos = sum(1 for i in rep.issues if i.severity == 'info')
                console.key_value(
                    'Валидация',
                    f"{console.colored('✖ ' + str(errs), Color.BRIGHT_RED) if errs else console.colored('0', Color.BRIGHT_GREEN)} ошибок, "
                    f"{console.colored('⚠ ' + str(warns), Color.BRIGHT_YELLOW) if warns else '0'} предупр., "
                    f"{infos} заметок",
                )
            except Exception:
                pass

            # Миграции
            if vm:
                mig_dir = p.migrations_for(driver)
                if mig_dir:
                    from lib.plugins.migrations import MigrationRunner
                    runner = MigrationRunner(p, driver, db)
                    status = runner.status()
                    if status:
                        rows = []
                        for m in status:
                            mark = ('✔' if m['applied']
                                    else console.colored('·', Color.BRIGHT_BLACK))
                            applied_at = m.get('applied_at') or '—'
                            rows.append([m['name'], mark, str(applied_at)])
                        console.table(
                            headers=['Миграция', 'OK', 'Применена'],
                            rows=rows,
                            align=['l', 'c', 'l'],
                        )

            # Lock
            if lock.exists():
                locked = next(
                    (lp for lp in lock._data.get('plugins', [])
                     if lp['name'] == p.name), None
                )
                if locked:
                    cur = lock._hash_plugin(p.path)
                    match_lock = (cur == locked.get('checksum'))
                    console.key_value(
                        'Lock',
                        console.colored('совпадает',
                                        Color.BRIGHT_GREEN)
                        if match_lock
                        else console.colored('изменён',
                                             Color.BRIGHT_RED)
                    )

        # ─── Итог ───
        console.line()
        total = len(plugins)
        enabled = sum(1 for p in plugins if p.state in ('enabled', 'migrated', 'loaded'))
        errors = sum(1 for p in plugins if p.state == 'error')
        summary = (f"Всего: {total} | Активных: {enabled} | "
                   f"С ошибками: {errors}")
        if errors:
            console.error(summary)
        else:
            console.success(summary)

        # Общие рекомендации
        console.newline()
        console.comment("Заметки:")
        console.comment("  • Расхождение версии — выполните `plugin:upgrade`")
        console.comment("  • Ошибки валидации — `plugin:check`")
        console.comment("  • Изменён lock — `lock:update`")

        return 1 if errors else 0
    finally:
        if db:
            db.close()

def diff(context):
    """Показать изменения плагина относительно установленной версии/lock/git."""
    from pathlib import Path
    from lib.plugins import get_manager
    from lib.plugins.lock import PluginsLock
    from lib.plugins.diff import PluginDiffer
    from lib.console import Color

    args = context['args']
    root = Path(context['root_dir'])
    cfg = context['config']

    name = args.get('name')
    if not name:
        console.error("Использование: homer plugin:diff --name=<plugin> "
                      "[--content] [--from=X] [--to=Y]")
        return 1

    mgr = get_manager()
    mgr.discover(root / 'plugins', cfg)

    plugin_dir = root / 'plugins' / name
    if not plugin_dir.exists():
        console.error(f"Плагин '{name}' не найден")
        return 1

    lock = PluginsLock(root)

    differ = PluginDiffer(root, plugins_lock=lock)
    result = differ.diff(
        plugin_dir,
        from_version=args.get('from'),
        to_version=args.get('to'),
        include_content_diff=bool(args.get('content', False)),
    )

    # ─── Заголовок ───
    console.banner(
        f"plugin:diff — {name}",
        f"{result.from_version or '?'} → {result.to_version or '?'} "
        f"(источник: {result.source})",
    )

    if result.source == 'disk':
        console.warning(
            "Нет источника для сравнения (нет lock и git). "
            "Используйте `homer lock:update` для фиксации состояния."
        )

    # ─── Версия ───
    if result.from_version and result.to_version and \
            result.from_version != result.to_version:
        console.key_value('Версия',
                          f"{result.from_version} → {result.to_version}",
                          key_color=None) if False else \
        console.print(f"  {console.colored('Версия', Color.BOLD)}: "
                      f"{result.from_version} → "
                      f"{console.colored(result.to_version, Color.BRIGHT_GREEN)}")

    # ─── Требования ───
    if result.requires_changed:
        console.section("Requires")
        before = set(result.requires_before)
        after = set(result.requires_after)
        for r in sorted(after - before):
            console.print(f"  {console.colored('+', Color.BRIGHT_GREEN)} {r}")
        for r in sorted(before - after):
            console.print(f"  {console.colored('-', Color.BRIGHT_RED)} {r}")
        for r in sorted(before & after):
            console.print(f"    {r}")

    # ─── Миграции ───
    if (result.migrations_added or result.migrations_removed
            or result.migrations_modified):
        console.section("Миграции")
        for m in result.migrations_added:
            console.print(f"  {console.colored('+', Color.BRIGHT_GREEN)} {m}")
        for m in result.migrations_modified:
            console.print(f"  {console.colored('~', Color.BRIGHT_YELLOW)} {m}")
        for m in result.migrations_removed:
            console.print(f"  {console.colored('-', Color.BRIGHT_RED)} {m}")
        console.newline()

    # ─── Файлы ───
    if result.files:
        console.section(f"Файлы ({len(result.files)})")
        for fd in result.files:
            if fd.status == 'added':
                mark = console.colored('+', Color.BRIGHT_GREEN)
            elif fd.status == 'deleted':
                mark = console.colored('-', Color.BRIGHT_RED)
            else:
                mark = console.colored('~', Color.BRIGHT_YELLOW)
            console.print(f"  {mark} {fd.path}")

            if fd.unified:
                console.print('')
                for line in fd.unified.splitlines():
                    if line.startswith('+++') or line.startswith('---'):
                        color = Color.BOLD
                    elif line.startswith('+'):
                        color = Color.BRIGHT_GREEN
                    elif line.startswith('-'):
                        color = Color.BRIGHT_RED
                    elif line.startswith('@@'):
                        color = Color.BRIGHT_CYAN
                    else:
                        color = Color.WHITE
                    console.print('    ' + console.colored(line, color))
                console.print('')

    # ─── Итог ───
    console.line()
    if not (result.files or result.migrations_added or
            result.migrations_modified or result.migrations_removed or
            result.requires_changed):
        console.success("Изменений не обнаружено")
        return 0

    added = sum(1 for f in result.files if f.status == 'added')
    removed = sum(1 for f in result.files if f.status == 'deleted')
    modified = sum(1 for f in result.files if f.status == 'modified')

    console.print(
        f"  Файлы: {console.colored('+' + str(added), Color.BRIGHT_GREEN)} "
        f"{console.colored('~' + str(modified), Color.BRIGHT_YELLOW)} "
        f"{console.colored('-' + str(removed), Color.BRIGHT_RED)}   "
        f"Миграции: "
        f"{console.colored('+' + str(len(result.migrations_added)), Color.BRIGHT_GREEN)} "
        f"{console.colored('~' + str(len(result.migrations_modified)), Color.BRIGHT_YELLOW)} "
        f"{console.colored('-' + str(len(result.migrations_removed)), Color.BRIGHT_RED)}"
    )
    return 0

def keygen(context):
    """Сгенерировать ed25519-ключи для подписи плагинов."""
    from pathlib import Path
    from lib.plugins.signing import generate_keypair, SignatureError

    args = context['args']
    key_id = args.get('key_id') or 'publisher@example.com'
    out_dir = Path(args.get('out') or (Path(context['root_dir']) / 'keys'))
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        priv_pem, pub_pem = generate_keypair(key_id)
    except SignatureError as e:
        console.error(str(e))
        return 1

    priv_path = out_dir / f'{key_id.replace("@", "_at_")}.key'
    pub_path = out_dir / f'{key_id.replace("@", "_at_")}.pub'
    priv_path.write_text(priv_pem, encoding='utf-8')
    pub_path.write_text(pub_pem, encoding='utf-8')
    try:
        priv_path.chmod(0o600)
    except Exception:
        pass

    console.success("Ключи сгенерированы")
    console.key_value('key_id', key_id)
    console.key_value('Приватный', str(priv_path))
    console.key_value('Публичный', str(pub_path))
    console.newline()
    console.comment("Приватный ключ — держите в секрете, НЕ коммитьте.")
    console.comment("Публичный — добавьте в plugins.pubkeys или config.yml:")
    console.comment(f"  plugins:\n    pubkeys:\n      {key_id}: |")
    for line in pub_pem.strip().splitlines():
        console.comment(f"        {line}")
    return 0


def sign(context):
    """Подписать плагин."""
    from pathlib import Path
    from lib.plugins.signing import cmd_sign, SignatureError

    args = context['args']
    name = args.get('name')
    key_path = args.get('key')
    key_id = args.get('key_id') or 'publisher@example.com'

    if not name or not key_path:
        console.error(
            "Использование: homer plugin:sign --name=<plugin> "
            "--key=<path-to-private.pem> [--key-id=publisher@example.com]"
        )
        return 1

    root = Path(context['root_dir'])
    plugin_dir = root / 'plugins' / name
    if not plugin_dir.exists():
        console.error(f"Плагин '{name}' не найден")
        return 1

    try:
        info = cmd_sign(plugin_dir, Path(key_path), key_id)
    except SignatureError as e:
        console.error(str(e))
        return 1
    except FileNotFoundError:
        console.error(f"Ключ не найден: {key_path}")
        return 1

    console.success(f"Плагин '{name}' подписан")
    console.key_value('key_id', info.key_id)
    console.key_value('checksum', info.signed_files_checksum)
    console.key_value('signed_at', info.signed_at)
    console.comment(f"Подпись: plugins/{name}/plugin.sig")
    return 0


def verify(context):
    """Проверить подпись плагина."""
    from pathlib import Path
    from lib.plugins.signing import (
        TrustStore, verify_plugin, load_signature, SignatureError,
    )

    args = context['args']
    name = args.get('name')
    if not name:
        console.error("Использование: homer plugin:verify --name=<plugin> "
                      "[--key=<path-to-public.pem>]")
        return 1

    root = Path(context['root_dir'])
    plugin_dir = root / 'plugins' / name
    if not plugin_dir.exists():
        console.error(f"Плагин '{name}' не найден")
        return 1

    key_path = args.get('key')

    try:
        if key_path:
            pub_pem = Path(key_path).read_text(encoding='utf-8')
            info = verify_plugin(plugin_dir, pub_pem)
        else:
            store = TrustStore(root, context['config'])
            info = store.verify(plugin_dir)
    except SignatureError as e:
        console.error(str(e))
        return 1

    console.section(f"Подпись — {name}")
    console.key_value('Алгоритм', info.algorithm)
    console.key_value('key_id', info.key_id)
    console.key_value('signed_at', info.signed_at or '—')
    console.key_value('checksum', info.signed_files_checksum)

    if info.valid and info.trusted is not False:
        console.success("Подпись действительна и доверенная")
        return 0
    if info.valid:
        console.warning("Подпись действительна, но ключ не в списке доверенных")
        return 0
    console.error(f"Подпись недействительна: {info.error}")
    return 1

def _get_registry(context):
    from pathlib import Path
    from lib.plugins.registry import Registry, RegistryError

    cfg = context['config']
    source = cfg.get('plugins.registry_url') or cfg.get('plugins.registry')
    if not source:
        console.error(
            "Не задан реестр. Добавьте в config.yml:\n"
            "  plugins:\n"
            "    registry: https://plugins.example.com/registry.json"
        )
        return None

    ttl = int(cfg.get('plugins.registry_ttl', 3600))
    root = Path(context['root_dir'])
    try:
        return Registry(root, source, cache_ttl=ttl)
    except RegistryError as e:
        console.error(str(e))
        return None


def search(context):
    """Поиск плагинов в marketplace."""
    reg = _get_registry(context)
    if reg is None:
        return 1

    args = context['args']
    tag = args.get('tag')
    query = args.get('q') or args.get('_positional', [None])[0]

    try:
        plugins = reg.list_plugins(tag=tag, search=query)
    except Exception as e:
        console.error(str(e))
        return 1

    if not plugins:
        console.warning("Плагины не найдены")
        return 0

    rows = []
    for p in plugins:
        latest = p.latest()
        rows.append([
            p.name,
            latest.version if latest else '—',
            p.description[:50],
            ', '.join(p.tags[:4]),
        ])
    console.table(
        headers=['Плагин', 'Версия', 'Описание', 'Теги'],
        rows=rows,
        align=['l', 'l', 'l', 'l'],
    )
    console.newline()
    console.comment("Установка: homer plugin:install --from-registry=<name>")
    return 0


def info_registry(context):
    """Инфо о плагине из marketplace."""
    reg = _get_registry(context)
    if reg is None:
        return 1

    name = context['args'].get('name') or \
           (context['args'].get('_positional') or [None])[0]
    if not name:
        console.error("Укажите --name=<plugin>")
        return 1

    try:
        p = reg.get_plugin(name)
    except Exception as e:
        console.error(str(e))
        return 1

    if not p:
        console.error(f"Плагин '{name}' не найден в реестре")
        return 1

    console.banner(f"Marketplace: {p.name}",
                   p.description or '(без описания)')
    console.key_value('Автор', p.author or '—')
    console.key_value('Homepage', p.homepage or '—')
    console.key_value('Теги', ', '.join(p.tags) or '—')

    console.section("Версии")
    rows = []
    for v in sorted(p.versions, key=lambda x: parse_version(x.version),
                    reverse=True):
        rows.append([
            v.version,
            v.requires_homer or '—',
            ', '.join(v.requires) or '—',
            v.released_at or '—',
            v.signature_key_id or '—',
        ])
    console.table(
        headers=['Версия', 'Требует Homer', 'Зависимости',
                 'Выпущена', 'Ключ'],
        rows=rows,
        align=['l', 'l', 'l', 'l', 'l'],
    )
    return 0
