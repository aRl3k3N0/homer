
from lib.console import console, Color

DESCRITOPN = "Test progres"

def execute(context):
    """
    context содержит:
      - config:       объект Config
      - logger:       объект Logger
      - args:         словарь аргументов ({args_example})
      - root_dir:     путь к корню проекта
      - command_name: имя команды
      - queue:        диспетчер очереди (ленивый)
    """
    logger = context['logger']
    config = context['config']
    args = context['args']
    command = context['command_name']

    logger.info(f"Running the command {command}", command=command)

    console.newline()
    import time
    items = list(range(100))

    with console.progress_ctx(len(items), prefix='Обработка',
                              show_eta=True) as bar:
        for i in range(1, 51):
            time.sleep(0.05)
            print(f"Обработка {i}")
            #console.progress(i, 50, prefix='Обработка')
            bar.update()

    console.panel(
        "IDM успешно завершена\nОбработано записей: 1268757684",
        title="Результат",
        color=Color.BRIGHT_GREEN
    )

    # TODO: реализуйте логику

    console.info(f"The {command} command has been executed.")
    return 0
