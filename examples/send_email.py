"""
send-email — пример отправки письма по шаблону.
"""
from datetime import datetime
from lib.mailer import Mailer

DESCRIPTION = "Отправить письмо по шаблону welcome"


def execute(context):
    config = context['config']
    logger = context['logger']
    command = context['command_name']
    args = context['args']

    to = args.get('to')
    if not to:
        print("Укажите --to=user@example.com")
        return 1

    mailer = Mailer(config, context['root_dir'] / 'email')
    mailer.send(
        to=to,
        template_name='welcome',
        context={
            'user': args.get('user', to),
            'version': config.get('app.version', '1.0'),
            'date': datetime.now(),
        },
    )
    logger.info(f"Письмо отправлено на {to}", command=command)
    print(f"✅ Письмо отправлено на {to}")
    return 0