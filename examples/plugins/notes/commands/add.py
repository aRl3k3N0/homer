"""notes:add — добавить заметку."""
from datetime import datetime
from lib.i18n import t

DESCRIPTION = "Добавить заметку"


def execute(context):
    args = context['args']
    title = args.get('title')
    body = args.get('body', '')

    if not title:
        print(t('notes.errors.title_required'))
        return 1

    from lib.db import connect
    cfg = context['config']
    driver = cfg.get('scheduler.storage', 'sqlite')
    conn_cfg = cfg.get(f'scheduler.{driver}') or cfg.get(f'databases.{driver}')
    if driver == 'sqlite':
        if not conn_cfg:
            conn_cfg = {'path': 'var/scheduler.db'}
        elif 'path' not in conn_cfg:
            conn_cfg = dict(conn_cfg, path='var/scheduler.db')

    with connect(driver, conn_cfg) as db:
        db.execute(
            "INSERT INTO notes_data (title, body, created_at) "
            "VALUES (" + db.placeholder(0) + ", "
                     + db.placeholder(1) + ", "
                     + db.placeholder(2) + ")",
            [title, body, datetime.now()],
        )
        db.commit()

    print(t('notes.created', title=title))
    return 0
