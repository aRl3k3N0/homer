"""
Просмотр и очистка истории запусков Web UI Console.
"""
from homer.core.console import console, Color

DESCRIPTION = "Web UI Console launch history"


def execute(context):
    args = context['args']
    action = args.get('_positional', ['list'])[0] if args.get('_positional') else 'list'

    from homer.webui.history import HistoryStorage
    storage = HistoryStorage(context['config'])
    try:
        if action == 'list':
            user = args.get('user')
            command = args.get('command')
            limit = int(args.get('limit', 50))
            entries = storage.list(user=user, command=command, limit=limit)
            if not entries:
                console.warning("The history is empty.")
                return 0
            rows = []
            for e in entries:
                rows.append([
                    e.started_at.strftime('%Y-%m-%d %H:%M:%S') if e.started_at else '—',
                    e.user,
                    e.command,
                    str(e.args)[:40],
                    console.colored(str(e.exit_code),
                                    Color.BRIGHT_GREEN if e.exit_code == 0
                                    else Color.BRIGHT_RED)
                    if e.exit_code is not None else '—',
                    f"{e.duration_ms} мс" if e.duration_ms else '—',
                ])
            console.table(
                headers=['When', 'User', 'Team', 'Arguments',
                         'Exit', 'Duration'],
                rows=rows,
                align=['l', 'l', 'l', 'l', 'r', 'r'],
            )

        elif action == 'purge':
            older = int(args.get('older', 86400 * 30))
            n = storage.purge_older_than(older)
            console.success(f"{n} records have been deleted.")

        else:
            console.error(f"Unknown action: {action}. "
                          f"Use: list | purge")
            return 1
    finally:
        storage.close()
    return 0
