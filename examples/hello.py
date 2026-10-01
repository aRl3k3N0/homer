"""
hello — минимальная команда Homer.
"""
DESCRIPTION = "Поздороваться с пользователем"


def execute(context):
    logger = context['logger']
    args = context['args']
    command = context['command_name']

    name = args.get('name', 'world')
    shout = bool(args.get('shout', False))

    logger.info(f"hello: name={name}, shout={shout}", command=command)

    greeting = f"Привет, {name}!"
    print(greeting.upper() if shout else greeting)

    return 0