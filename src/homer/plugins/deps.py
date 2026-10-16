"""
Разрешение зависимостей между плагинами.

- Топологическая сортировка (Kahn's algorithm).
- Обнаружение циклов.
- Проверка semver-совместимости requires_homer.
- Проверка версий required plugins (>=).
"""

from __future__ import annotations

import re
from typing import Optional

from .plugin import PluginInfo


class DependencyError(Exception):
    pass


class VersionConstraintError(DependencyError):
    pass


# ─────────── Semver ───────────

_SEMVER_RE = re.compile(
    r'^(?P<major>0|[1-9]\d*)'
    r'\.(?P<minor>0|[1-9]\d*)'
    r'\.(?P<patch>0|[1-9]\d*)'
    r'(?:-(?P<pre>[0-9A-Za-z.\-]+))?'
    r'(?:\+(?P<build>[0-9A-Za-z.\-]+))?$'
)


def parse_version(s: str) -> tuple[int, int, int, str]:
    """
    Возвращает (major, minor, patch, pre). pre='' для релизов.
    Некорректная строка → (0,0,0, s).
    """
    m = _SEMVER_RE.match(s.strip())
    if not m:
        return (0, 0, 0, s)
    return (
        int(m.group('major')),
        int(m.group('minor')),
        int(m.group('patch')),
        m.group('pre') or '',
    )


def _cmp_versions(a: str, b: str) -> int:
    """-1 если a<b, 0 если равны, 1 если a>b. Учитывает pre-release."""
    va, vb = parse_version(a), parse_version(b)
    for i in range(3):
        if va[i] != vb[i]:
            return -1 if va[i] < vb[i] else 1
    # Если у одного pre, у другого нет — релиз > pre-release
    if va[3] and not vb[3]:
        return -1
    if not va[3] and vb[3]:
        return 1
    if va[3] == vb[3]:
        return 0
    return -1 if va[3] < vb[3] else 1


def satisfies(version: str, constraint: str) -> bool:
    """
    Проверка ограничения. Поддерживаются:
        '1.2.3'        — точное
        '>=1.2.3'      — не меньше
        '>1.2.3'       — больше
        '<=1.2.3'      — не больше
        '<1.2.3'       — меньше
        '~1.2.3'       — совместимо (>=1.2.3, <1.3.0)
        '^1.2.3'       — совместимо (>=1.2.3, <2.0.0)
        '>=1.0,<2.0'   — диапазон через запятую
        '*'            — любая
    """
    constraint = (constraint or '').strip()
    if not constraint or constraint == '*':
        return True

    # Несколько условий через запятую — все должны пройти
    if ',' in constraint:
        return all(satisfies(version, c.strip()) for c in constraint.split(','))

    # Тильда
    if constraint.startswith('~'):
        base = parse_version(constraint[1:])
        v = parse_version(version)
        if _cmp_versions(version, '.'.join(map(str, base[:3]))) < 0:
            return False
        upper = (base[0], base[1] + 1, 0)
        return _cmp_versions(version, '.'.join(map(str, upper))) < 0

    # Каретка
    if constraint.startswith('^'):
        base = parse_version(constraint[1:])
        v = parse_version(version)
        if _cmp_versions(version, '.'.join(map(str, base[:3]))) < 0:
            return False
        if base[0] > 0:
            upper = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            upper = (0, base[1] + 1, 0)
        else:
            upper = (0, 0, base[2] + 1)
        return _cmp_versions(version, '.'.join(map(str, upper))) < 0

    # Операторы
    for op in ('>=', '<=', '>', '<', '=='):
        if constraint.startswith(op):
            target = constraint[len(op) :].strip()
            c = _cmp_versions(version, target)
            if op == '>=':
                return c >= 0
            if op == '<=':
                return c <= 0
            if op == '>':
                return c > 0
            if op == '<':
                return c < 0
            if op == '==':
                return c == 0

    # Точное совпадение
    return _cmp_versions(version, constraint) == 0


# ─────────── Граф зависимостей ───────────


def resolve(
    plugins: dict[str, PluginInfo], homer_version: Optional[str] = None
) -> list[PluginInfo]:
    """
    Топологическая сортировка плагинов с учётом 'requires'.

    plugins       — {name: PluginInfo}
    homer_version — если задано, проверяем requires_homer

    Возвращает список PluginInfo в порядке загрузки (зависимости первыми).

    Бросает DependencyError при:
      - отсутствии зависимости,
      - цикле,
      - несовместимой версии (requires_homer или requires с версией).
    """
    # Нормализуем requires: может быть ["a", "b>=1.0"] или
    # [{"name": "a", "version": ">=1.0"}]
    graph: dict[str, list[tuple[str, Optional[str]]]] = {}
    for name, p in plugins.items():
        deps: list[tuple[str, Optional[str]]] = []
        for req in p.requires or []:
            if isinstance(req, dict):
                deps.append((req.get('name', ''), req.get('version', '')))
            elif isinstance(req, str):
                # "a>=1.0" | "a" | "a==1.2.3"
                for op in ('>=', '<=', '==', '>', '<', '~', '^'):
                    if op in req:
                        n, _, v = req.partition(op)
                        deps.append((n.strip(), f"{op}{v.strip()}"))
                        break
                else:
                    deps.append((req.strip(), ''))
            else:
                raise DependencyError(f"Плагин '{name}': неверный формат requires")
        graph[name] = deps

    # 1) Проверка наличия всех зависимостей и их версий
    for name, deps in graph.items():
        for dep_name, constraint in deps:
            if not dep_name:
                raise DependencyError(f"Плагин '{name}': пустая зависимость")
            if dep_name not in plugins:
                raise DependencyError(
                    f"Плагин '{name}' требует '{dep_name}', но он не найден в plugins/"
                )
            if constraint:
                actual = plugins[dep_name].version or '0.0.0'
                if not satisfies(actual, constraint):
                    raise VersionConstraintError(
                        f"Плагин '{name}' требует '{dep_name} {constraint}', а установлен {actual}"
                    )

    # 2) requires_homer
    if homer_version:
        for name, p in plugins.items():
            if p.requires_homer and not satisfies(homer_version, p.requires_homer):
                raise VersionConstraintError(
                    f"Плагин '{name}' требует Homer {p.requires_homer}, "
                    f"текущая версия {homer_version}"
                )

    # 3) Топосортировка (Kahn)
    indeg: dict[str, int] = dict.fromkeys(plugins, 0)
    adj: dict[str, list[str]] = {n: [] for n in plugins}
    for name, deps in graph.items():
        for dep_name, _ in deps:
            adj[dep_name].append(name)
            indeg[name] += 1

    queue = [n for n, d in indeg.items() if d == 0]
    queue.sort()  # стабильность

    ordered: list[str] = []
    while queue:
        n = queue.pop(0)
        ordered.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
                queue.sort()

    if len(ordered) != len(plugins):
        # Цикл — найдём хотя бы одну петлю
        remaining = [n for n in plugins if n not in ordered]
        cycle = _find_cycle(graph, remaining)
        raise DependencyError(
            f"Обнаружен цикл зависимостей: {' → '.join(cycle) if cycle else ', '.join(remaining)}"
        )

    return [plugins[n] for n in ordered]


def _find_cycle(
    graph: dict[str, list[tuple[str, Optional[str]]]], candidates: list[str]
) -> list[str]:
    """Ищет любой цикл среди candidates."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)
    stack: list[str] = []

    def dfs(n: str) -> Optional[list[str]]:
        color[n] = GRAY
        stack.append(n)
        for dep_name, _ in graph.get(n, []):
            if dep_name not in color:
                continue
            if color[dep_name] == GRAY:
                # цикл
                i = stack.index(dep_name)
                return stack[i:] + [dep_name]
            if color[dep_name] == WHITE:
                result = dfs(dep_name)
                if result:
                    return result
        stack.pop()
        color[n] = BLACK
        return None

    for n in candidates:
        if color.get(n) == WHITE:
            r = dfs(n)
            if r:
                return r
    return []
