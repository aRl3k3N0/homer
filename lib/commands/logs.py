"""
logs — работа с логами: list, tail, export.
"""
from pathlib import Path

from lib.console import console, Color

DESCRIPTION = "Viewing and exporting logs"


def execute(context):
    args = context['args']
    action = (args.get('_positional') or ['list'])[0]
    root = Path(context['root_dir'])
    logs_dir = root / 'logs'

    from lib.webui.logs_reader import LogsReader
    reader = LogsReader(logs_dir)

    if action == 'list':
        files = reader.list_files()
        if not files:
            console.warning("There are no logs.")
            return 0
        rows = [
            [f.command, f.date.isoformat(), _fmt_size(f.size)]
            for f in files[:100]
        ]
        console.table(
            headers=['Team', 'Date', 'Size'],
            rows=rows,
            align=['l', 'l', 'r'],
        )

    elif action == 'tail':
        command = args.get('command')
        date_ = args.get('date')
        limit = int(args.get('limit', 50))
        if not command or not date_:
            console.error("Are needed --command and --date")
            return 1
        entries = reader.read(command, date_, limit=limit)
        for e in entries:
            ts = e.ts.strftime('%H:%M:%S') if e.ts else '--:--:--'
            color = {
                'DEBUG': Color.BRIGHT_BLACK,
                'INFO': Color.WHITE,
                'WARNING': Color.BRIGHT_YELLOW,
                'ERROR': Color.BRIGHT_RED,
                'CRITICAL': Color.BRIGHT_MAGENTA,
            }.get(e.level, Color.WHITE)
            print(f"{console.colored(ts, Color.BRIGHT_BLACK)} "
                  f"{console.colored(f'[{e.level:<8}]', color)} {e.message}")

    elif action == 'export':
        command = args.get('command')
        date_ = args.get('date')
        fmt = args.get('format', 'jsonl')
        out = args.get('out') or f"{command}_{date_}.{fmt}"

        if not command or not date_:
            console.error("Нужны --command и --date")
            return 1

        entries = reader.read(command, date_, tail=False)
        out_path = Path(out)

        if fmt == 'jsonl':
            with open(out_path, 'w', encoding='utf-8') as f:
                for e in entries:
                    import json
                    f.write(json.dumps({
                        'ts': e.ts.isoformat() if e.ts else None,
                        'level': e.level,
                        'message': e.message,
                    }, ensure_ascii=False) + '\n')
        elif fmt == 'json':
            import json
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump([{
                    'ts': e.ts.isoformat() if e.ts else None,
                    'level': e.level,
                    'message': e.message,
                } for e in entries], f, ensure_ascii=False, indent=2)
        elif fmt == 'csv':
            import csv
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                w = csv.writer(f)
                w.writerow(['ts', 'level', 'message'])
                for e in entries:
                    w.writerow([e.ts.isoformat() if e.ts else '',
                                e.level, e.message])
        else:
            console.error("--format=json|jsonl|csv")
            return 1

        console.success(f"{len(entries)} rows have been exported to {out_path}")

    else:
        console.error(f"Unknown action: {action}")
        return 1

    return 0


def _fmt_size(n):
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"
