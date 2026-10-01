"""
send-telegram — пример отправки уведомления в Telegram.
"""
from datetime import datetime
from lib.notify.base import NotifyEvent
from lib.notify.telegram_notifier import TelegramNotifier

DESCRIPTION = "Отправить произвольное уведомление в Telegram"


def execute(context):
    config = context['config']
    args = context['args']

    text = args.get('text', 'Привет из Homer!')

    notifier = TelegramNotifier(config)

    event = NotifyEvent(
        job_id=0,
        command=context['command_name'],
        args={'text': text},
        status='failed',                    # любой статус; on проверять не будем
        exit_code=1,
        error=text,
        result=None,
        duration_sec=None,
        triggered_by='cli',
        attempts=1,
        max_attempts=1,
        started_at=datetime.now(),
        finished_at=datetime.now(),
    )

    # Принудительно шлём, минуя фильтр on
    notifier.on = [event.status]
    notifier.send(event)
    print("✅ Уведомление отправлено")
    return 0