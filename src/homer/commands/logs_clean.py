"""
logs:clean — чистка старых логов по настройкам из config.yml.

Настройки:
    logging.retention.default_days: 90
    logging.retention.per_command:
      webui: 30
      scheduler: 30
"""
from datetime import date, datetime, timedelta
from pathlib import Path

from homer.core.console import console, Color
from homer.core.paths import log_dir


DESCRIPTION = "Delete outdated logs according to the rules from config.yml"


def _retention_for(config, command: str) -> int:
    """Возвращает число дней хранения для команды."""
    cfg = config.get('logging.retention', {}) or {}
    default_days = int(cfg.get('default_days', 90))
    per = cfg.get('per_command', {}) or {}
    if command in per:
        try:
            return int(per[command])
        except (TypeError, ValueError):
            pass
    return default_days


def _scan(base: Path):
    """Возвращает [(command, date, path, size)]."""
    result = []
    if not base.exists():
        return result
    for cmd_dir in base.iterdir():
        if not cmd_dir.is_dir():
            continue
        for f in cmd_dir.glob('*.log'):
            try:
                d = datetime.strptime(f.stem, '%Y-%m-%d').date()
            except ValueError:
                continue
            result.append((cmd_dir.name, d, f, f.stat().st_size))
    return result


def _fmt_size(n: int) -> str:
    for unit in ('B', 'K', 'M', 'G'):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def execute(context):
    args = context['args']
    config = context['config']
    root = Path(context['root_dir'])

    base = log_dir(config, root)

    # --dry-run по умолчанию; удаляем только с --apply
    apply_ = bool(args.get('apply', False))
    # Ограничение по команде: --command=webui
    only_command = args.get('command')
    # Принудительное переопределение срока: --days=30
    override_days = args.get('days')
    try:
        override_days = int(override_days) if override_days is not None else None
    except (TypeError, ValueError):
        console.error("--days must be a number")
        return 1

    today = date.today()
    files = _scan(base)

    to_delete = []
    to_keep = []

    for command, d, path, size in files:
        if only_command and command != only_command:
            continue
        days = override_days if override_days is not None else _retention_for(config, command)
        cutoff = today - timedelta(days=days)
        if d < cutoff:
            to_delete.append((command, d, path, size))
        else:
            to_keep.append((command, d, path, size, days))

    console.banner("logs:clean", f"{base}")

    # Сводка по командам
    console.section("Keeping")
    seen = {}
    for command, _, _, _, days in to_keep:
        seen[command] = days
    for command in sorted(seen):
        console.key_value(command, f"{seen[command]} days")

    # Что удалим
    console.section(f"To delete ({len(to_delete)} files)")
    if not to_delete:
        console.success("There’s nothing to delete.")
        return 0

    total_size = 0
    by_command = {}
    for command, d, path, size in to_delete:
        by_command.setdefault(command, []).append((d, size))
        total_size += size

    rows = []
    for command in sorted(by_command):
        items = by_command[command]
        rows.append([
            command,
            str(len(items)),
            _fmt_size(sum(s for _, s in items)),
            min(d for d, _ in items).isoformat(),
            max(d for d, _ in items).isoformat(),
        ])

    console.table(
        headers=['Command', 'File', 'Size', 'After', 'Before'],
        rows=rows,
        align=['l', 'r', 'r', 'l', 'l'],
    )

    console.newline()
    console.key_value('Total files', len(to_delete))
    console.key_value('Total size', _fmt_size(total_size))

    if not apply_:
        console.comment("Dry-run. For removal: logs:clean --apply")
        return 0

    # ─── Удаление ───
    if not console.confirm(f"Delete {len(to_delete)} files?", default=False):
        console.comment("Cancelled")
        return 0

    removed = 0
    removed_size = 0
    errors = []

    for command, d, path, size in to_delete:
        try:
            path.unlink()
            removed += 1
            removed_size += size
        except Exception as e:
            errors.append((path, str(e)))

    # Удаляем пустые каталоги команд
    for cmd_dir in base.iterdir():
        if not cmd_dir.is_dir():
            continue
        try:
            if not any(cmd_dir.iterdir()):
                cmd_dir.rmdir()
        except Exception:
            pass

    console.success(
        f"{removed} files ({_fmt_size(removed_size)})"
    )
    if errors:
        console.warning(f"Error: {len(errors)}")
        for path, err in errors[:10]:
            console.print(f"  {path}: {err}")
    return 0
