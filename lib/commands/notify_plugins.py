"""Список нотификаторов (встроенных и плагинов)."""
from lib.console import console, Color

DESCRIPTION = "Show the list of notifiers (including plugins)"


def execute(context):
    from lib.notify import REGISTRY

    # Определим, что «встроено» (модуль из lib.notify.*)
    builtin_prefix = 'lib.notify'
    rows = []
    for name, cls in sorted(REGISTRY.items()):
        module = cls.__module__ or ''
        kind = 'built‑in' if module.startswith(builtin_prefix) else 'plugin'
        rows.append([name, f"{cls.__module__}.{cls.__name__}", kind])

    console.banner("Notifiers")
    console.table(
        headers=['Name', 'Class', 'Type'],
        rows=rows,
        align=['l', 'l', 'c'],
    )
    return 0
