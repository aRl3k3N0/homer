"""
Генератор команд Homer.
Создаёт файл(ы) в директории commands.
"""
from pathlib import Path

from lib.console import console


DESCRIPTION = "Create a new command (template .py)"


TEMPLATE_COMMAND = '''"""
{title}
"""
from lib.console import console

DESCRIPTION = "{description}"


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

    # TODO: реализуйте логику

    console.info(f"The {name} command has been executed.")
    return 0
'''


def execute(context):
    args = context['args']
    root_dir = Path(context['root_dir'])

    name = args.get('name')
    force = bool(args.get('force', False))

    if not name:
        console.error(
            "Specify the command name.: homer make:command --name=report:daily"
        )
        return 1

    # Нормализуем: ':' → '/', убираем .py
    name = str(name).replace('\\', '/').replace(':', '/')
    if name.endswith('.py'):
        name = name[:-3]

    rel_parts = [p for p in name.split('/') if p]
    if not rel_parts:
        console.error("Incorrect command name")
        return 1

    for part in rel_parts:
        if not part.replace('_', '').replace('-', '').isalnum():
            console.error(
                f"Invalid part name: '{part}'. "
                f"Use letters, numbers, _ and -"
            )
            return 1

    file_parts = rel_parts

    target_dir = root_dir / 'commands' / Path(*file_parts[:-1])
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / f"{file_parts[-1]}.py"
    if target_file.exists() and not force:
        console.error(f"The file already exists.: {target_file}")
        console.comment("Use --force to overwrite.")
        return 1

    # Гарантируем __init__.py во всех промежуточных директориях
    cur = root_dir / 'commands'
    if not (cur / '__init__.py').exists():
        (cur / '__init__.py').write_text(
            '"""Custom commands Homer."""\n', encoding='utf-8'
        )
    for part in file_parts[:-1]:
        cur = cur / part
        init = cur / '__init__.py'
        if not init.exists():
            init.write_text('"""Command package Homer."""\n', encoding='utf-8')

    command_name = ':'.join(rel_parts)
    description = args.get('description') or f"Team {command_name}"
    args_example = args.get('args_example') or "'user': 'admin', 'ver': '1.0'"

    content = TEMPLATE_COMMAND.format(
        title=f"{command_name} — {description}",
        description=description,
        name=command_name,
        args_example=args_example,
    )

    target_file.write_text(content, encoding='utf-8')

    console.success(f"A team has been created. {console.bold(command_name)}")
    console.key_value('File', str(target_file.relative_to(root_dir)))
    console.comment(f"Launch: homer {command_name}")
    return 0
