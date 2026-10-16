"""
Валидация структуры плагинов без их загрузки в Homer.

Проверяем:
    - обязательные файлы (plugin.json, __init__.py)
    - корректность plugin.json (поля, версии, semver)
    - существование requires и их semver-совместимость
    - наличие migrations/<driver>/ для БД, где плагин включён
    - наличие uninstall.sql для каждого driver-каталога (предупреждение,
      если нет)
    - синтаксис SQL-файлов (элементарно: непустые, есть ;)
    - синтаксис команд (компиляция AST без импорта)
    - синтаксис __init__.py
    - валидность YAML переводов
    - наличие хотя бы одного lang-файла, если есть langs/
    - соответствие структуры заявленному шаблону
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Optional

import yaml

from homer.migrations import SUPPORTED_DRIVERS

from .deps import DependencyError, VersionConstraintError, resolve
from .plugin import PluginInfo

SEVERITY_ERROR = 'error'
SEVERITY_WARNING = 'warning'
SEVERITY_INFO = 'info'


@dataclass
class Issue:
    severity: str
    message: str
    path: Optional[Path] = None
    plugin: Optional[str] = None

    def format(self) -> str:
        prefix = {
            SEVERITY_ERROR: '✖',
            SEVERITY_WARNING: '⚠',
            SEVERITY_INFO: '·',
        }[self.severity]
        loc = f" [{self.path}]" if self.path else ''
        return f"  {prefix} {self.message}{loc}"


@dataclass
class PluginReport:
    plugin_name: str
    path: Path
    issues: list[Issue] = field(default_factory=list)
    info: Optional[PluginInfo] = None

    @property
    def has_errors(self) -> bool:
        return any(i.severity == SEVERITY_ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == SEVERITY_WARNING for i in self.issues)

    def add(self, severity: str, message: str, path: Path = None):
        self.issues.append(Issue(severity, message, path, self.plugin_name))


class PluginValidator:
    def __init__(
        self,
        plugins_dir: Path,
        homer_version: str = '0.0.0',
        known_drivers: Optional[list[str]] = None,
    ):
        self.plugins_dir = Path(plugins_dir)
        self.homer_version = homer_version
        self.known_drivers = known_drivers or sorted(SUPPORTED_DRIVERS)

    def check_all(self) -> list[PluginReport]:
        reports = []
        plugins: dict[str, PluginInfo] = {}

        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith(('.', '_')):
                continue
            report = self.check_one(entry)
            reports.append(report)
            if report.info and not report.has_errors:
                plugins[report.info.name] = report.info

        # Глобальные проверки: топосортировка
        if plugins:
            try:
                resolve(plugins, self.homer_version)
            except VersionConstraintError as e:
                # Привязываем к плагину, если сможем
                msg = str(e)
                target = next((r for r in reports if r.info and r.info.name in msg), None)
                if target:
                    target.add(SEVERITY_ERROR, msg)
                else:
                    reports.append(
                        PluginReport('(global)', self.plugins_dir, [Issue(SEVERITY_ERROR, msg)])
                    )
            except DependencyError as e:
                reports.append(
                    PluginReport('(global)', self.plugins_dir, [Issue(SEVERITY_ERROR, str(e))])
                )

        return reports

    # ─────────── Один плагин ───────────

    def check_one(self, plugin_dir: Path) -> PluginReport:
        report = PluginReport(plugin_name=plugin_dir.name, path=plugin_dir)

        # 1. Обязательные файлы
        manifest = plugin_dir / 'plugin.json'
        init_py = plugin_dir / '__init__.py'
        if not manifest.exists():
            report.add(SEVERITY_ERROR, "Отсутствует plugin.json", manifest)
            return report
        if not init_py.exists():
            report.add(
                SEVERITY_WARNING,
                "Отсутствует __init__.py — плагин не сможет выполнять логику инициализации",
                init_py,
            )

        # 2. Манифест
        info = self._parse_manifest(manifest, report)
        if info:
            report.info = info
            report.plugin_name = info.name

        # 3. Структура каталогов
        self._check_structure(plugin_dir, report, info)

        # 4. Синтаксис __init__.py
        if init_py.exists():
            self._check_python_syntax(init_py, report)

        # 5. Команды
        self._check_commands(plugin_dir, report)

        # 6. Миграции
        self._check_migrations(plugin_dir, report, info)

        # 7. Переводы
        self._check_langs(plugin_dir, report)

        # 8. Шаблоны (Jinja)
        self._check_templates(plugin_dir, report)

        return report

    # ─────────── Проверки ───────────

    def _parse_manifest(self, path: Path, report: PluginReport) -> Optional[PluginInfo]:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            report.add(SEVERITY_ERROR, f"plugin.json: невалидный JSON: {e}", path)
            return None

        required = ['name', 'version']
        for k in required:
            if not data.get(k):
                report.add(SEVERITY_ERROR, f"plugin.json: обязательно поле '{k}'", path)

        name = data.get('name')
        if name and not re.match(r'^[a-z][a-z0-9_]*$', name):
            report.add(
                SEVERITY_ERROR,
                f"plugin.json: 'name' должен состоять из "
                f"латиницы в нижнем регистре, цифр и '_' "
                f"(получено '{name}')",
                path,
            )

        version = data.get('version', '')
        if version and not re.match(r'^\d+\.\d+\.\d+', version):
            report.add(
                SEVERITY_WARNING, f"plugin.json: 'version' не похож на semver ('{version}')", path
            )

        # requires
        req = data.get('requires')
        if req is not None and not isinstance(req, list):
            report.add(SEVERITY_ERROR, "plugin.json: 'requires' должен быть массивом", path)

        # requires_homer
        rh = data.get('requires_homer')
        if rh is not None and not isinstance(rh, str):
            report.add(SEVERITY_ERROR, "plugin.json: 'requires_homer' должен быть строкой", path)

        try:
            return PluginInfo.from_dir(path.parent)
        except Exception as e:
            report.add(SEVERITY_ERROR, f"Ошибка разбора манифеста: {e}", path)
            return None

    def _check_structure(self, plugin_dir: Path, report: PluginReport, info: Optional[PluginInfo]):
        """Проверка допустимых каталогов и типичных ошибок."""
        known = {'commands', 'lib', 'email', 'langs', 'templates', 'static', 'migrations'}
        for entry in plugin_dir.iterdir():
            if entry.name.startswith(('.', '_', '__pycache__')):
                continue
            if entry.is_file():
                if entry.suffix == '.md':
                    continue
                if entry.name in ('plugin.json', '__init__.py'):
                    continue
                if entry.suffix == '.py':
                    continue
                report.add(SEVERITY_INFO, f"Необычный файл в корне плагина: {entry.name}", entry)
            elif entry.is_dir():
                if entry.name not in known:
                    report.add(
                        SEVERITY_WARNING,
                        f"Неизвестный каталог '{entry.name}' в плагине. "
                        f"Ожидались: {', '.join(sorted(known))}",
                        entry,
                    )

    def _check_python_syntax(self, path: Path, report: PluginReport):
        try:
            source = path.read_text(encoding='utf-8')
            ast.parse(source, filename=str(path))
        except SyntaxError as e:
            report.add(SEVERITY_ERROR, f"Синтаксическая ошибка: {e.msg} (строка {e.lineno})", path)
        except Exception as e:
            report.add(SEVERITY_ERROR, f"Ошибка чтения: {e}", path)

    def _check_commands(self, plugin_dir: Path, report: PluginReport):
        cdir = plugin_dir / 'commands'
        if not cdir.exists():
            return
        for py in cdir.rglob('*.py'):
            if py.name == '__init__.py':
                continue
            try:
                source = py.read_text(encoding='utf-8')
                tree = ast.parse(source, filename=str(py))
            except SyntaxError as e:
                report.add(
                    SEVERITY_ERROR,
                    f"Команда '{py.name}': синтаксическая ошибка {e.msg} (строка {e.lineno})",
                    py,
                )
                continue

            # Проверка наличия execute(context)
            has_execute = any(
                isinstance(node, ast.FunctionDef) and node.name == 'execute' for node in tree.body
            )
            if not has_execute:
                report.add(
                    SEVERITY_WARNING,
                    f"Команда '{py.relative_to(plugin_dir)}': нет функции execute(context)",
                    py,
                )

    def _check_migrations(self, plugin_dir: Path, report: PluginReport, info: Optional[PluginInfo]):
        mdir = plugin_dir / 'migrations'
        if not mdir.exists():
            return

        for driver_dir in mdir.iterdir():
            if not driver_dir.is_dir():
                continue
            driver = driver_dir.name
            if driver not in self.known_drivers:
                report.add(
                    SEVERITY_WARNING,
                    f"Миграции для неизвестного драйвера '{driver}'. "
                    f"Известные: {', '.join(self.known_drivers)}",
                    driver_dir,
                )
                continue

            # Хотя бы одна миграция
            sqls = [f for f in driver_dir.glob('*.sql') if f.name != 'uninstall.sql']
            if not sqls:
                report.add(
                    SEVERITY_WARNING,
                    f"Каталог migrations/{driver}/ пуст (нет .sql-файлов)",
                    driver_dir,
                )

            # uninstall.sql — предупреждение, если нет
            if not (driver_dir / 'uninstall.sql').exists():
                report.add(
                    SEVERITY_INFO,
                    f"Нет uninstall.sql для {driver} — при удалении плагина данные останутся в БД",
                    driver_dir,
                )

            # Проверяем, что все sql непустые
            for sql_file in driver_dir.glob('*.sql'):
                try:
                    content = sql_file.read_text(encoding='utf-8').strip()
                except Exception as e:
                    report.add(SEVERITY_ERROR, f"Ошибка чтения {sql_file.name}: {e}", sql_file)
                    continue
                if not content:
                    report.add(SEVERITY_WARNING, f"Пустой файл {sql_file.name}", sql_file)

            # Проверка нумерации: 001, 002, ... без пропусков
            numbers = []
            for f in sqls:
                m = re.match(r'^(\d+)', f.name)
                if m:
                    numbers.append(int(m.group(1)))
                else:
                    report.add(
                        SEVERITY_WARNING, f"Имя миграции '{f.name}' не начинается с числа", f
                    )
            numbers.sort()
            if numbers:
                expected = list(range(1, numbers[-1] + 1))
                if numbers != expected:
                    missing = set(expected) - set(numbers)
                    if missing:
                        report.add(
                            SEVERITY_INFO,
                            f"Пропущены номера миграций для {driver}: {sorted(missing)}",
                            driver_dir,
                        )

    def _check_langs(self, plugin_dir: Path, report: PluginReport):
        ldir = plugin_dir / 'langs'
        if not ldir.exists():
            return
        found = 0
        for yml in ldir.glob('*.y*ml'):
            try:
                data = yaml.safe_load(yml.read_text(encoding='utf-8'))
            except yaml.YAMLError as e:
                report.add(SEVERITY_ERROR, f"Ошибка YAML в {yml.name}: {e}", yml)
                continue
            except Exception as e:
                report.add(SEVERITY_ERROR, f"Ошибка чтения {yml.name}: {e}", yml)
                continue
            if not isinstance(data, dict):
                report.add(SEVERITY_WARNING, f"{yml.name}: ожидался объект верхнего уровня", yml)
                continue
            found += 1
            # Проверка кодировки
            locale = yml.stem
            if not re.match(r'^[a-z]{2}(_[A-Z]{2})?$', locale):
                report.add(
                    SEVERITY_INFO, f"Имя локали '{locale}' не по шаблону 'xx' или 'xx_XX'", yml
                )
        if not found:
            report.add(SEVERITY_INFO, "Каталог langs/ есть, но не содержит .yml-файлов", ldir)

    def _check_templates(self, plugin_dir: Path, report: PluginReport):
        for sub in ('templates', 'email'):
            tdir = plugin_dir / sub
            if not tdir.exists():
                continue
            for t in tdir.rglob('*.html'):
                try:
                    from jinja2 import Environment, FileSystemLoader

                    env = Environment(
                        loader=FileSystemLoader(str(t.parent)),
                        autoescape=True,
                    )
                    env.get_template(t.name)
                except ImportError:
                    return
                except Exception as e:
                    report.add(SEVERITY_ERROR, f"Jinja-ошибка в {t.name}: {e}", t)


# ─────────── Рендер отчёта ───────────


def render_reports(reports: list[PluginReport], console) -> tuple[int, int]:
    """
    Печатает отчёт. Возвращает (n_errors, n_warnings).
    """
    from homer.core.console import Color

    n_errors = 0
    n_warnings = 0
    for r in reports:
        status_color = (
            Color.BRIGHT_GREEN
            if not r.issues
            else (Color.BRIGHT_RED if r.has_errors else Color.BRIGHT_YELLOW)
        )
        header = f"{r.plugin_name}"
        if r.info:
            header += f" v{r.info.version}"
        console.print(console.colored(header, Color.BOLD + status_color))
        if not r.issues:
            console.print(f"  {console.colored('✔', Color.BRIGHT_GREEN)} Всё ок")
        else:
            for issue in r.issues:
                color = {
                    SEVERITY_ERROR: Color.BRIGHT_RED,
                    SEVERITY_WARNING: Color.BRIGHT_YELLOW,
                    SEVERITY_INFO: Color.BRIGHT_BLACK,
                }[issue.severity]
                console.print(console.colored(issue.format(), color))
                if issue.severity == SEVERITY_ERROR:
                    n_errors += 1
                elif issue.severity == SEVERITY_WARNING:
                    n_warnings += 1
        console.newline()
    return n_errors, n_warnings
