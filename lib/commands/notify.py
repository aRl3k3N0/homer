"""
Тест нотификаторов.
"""
from datetime import datetime

from lib.console import console

DESCRIPTION = "Send a test notification."


def test(context):
    from lib.notify import NotifyManager
    from lib.notify.base import NotifyEvent

    args = context['args']
    status = args.get('status', 'failed')

    mgr = NotifyManager(
        context['config'],
        logger=context['logger'],
        root_dir=context['root_dir'],
    )

    event = NotifyEvent(
        job_id=99999,
        command='demo:task',
        args={'user': 'admin', 'ver': 16},
        status=status,
        exit_code=1 if status != 'done' else 0,
        error=('Test error: something went wrong\nTraceback ...'
               if status != 'done' else None),
        result='Test output line 1\nline 2' if status == 'done' else None,
        duration_sec=12.34,
        triggered_by='notify:test',
        attempts=1,
        max_attempts=3,
        started_at=datetime.now(),
        finished_at=datetime.now(),
    )
    mgr.emit(event)
    console.success(f"The test event '{status}' has been sent "
                    f"({len(mgr.notifiers)} notifiers)")
    return 0
