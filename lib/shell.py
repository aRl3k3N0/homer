"""
Интерактивный REPL-режим Homer.

Позволяет вводить команды Homer без перезапуска приложения,
а также выполнять произвольный Python-код в контексте приложения.
"""

import code
import shlex
import traceback

from lib.console import Color, console


class HomerShell(code.InteractiveConsole):
    """
    Расширенный REPL с командами Homer.

    Специальные команды:
        :help              — справка
        :list              — список команд Homer
        :run <команда> ... — выполнить команду Homer
        :reload            — перечитать конфиг и команды
        :ctx               — показать текущий контекст
        :clear             — очистить экран
        :exit / :quit      — выйти
    """

    def __init__(self, context, command_loader, config):
        self.homer_context = context
        self.command_loader = command_loader
        self.config = config

        locals_dict = {
            'config': config,
            'console': console,
            'Color': Color,
            'logger': context['logger'],
            'root_dir': context['root_dir'],
            'commands': context.get('commands', {}),
            'ctx': context,
        }

        super().__init__(locals=locals_dict)

    # ─────────────────── Выполнение команды Homer ───────────────────

    def run_command(self, line):
        try:
            parts = shlex.split(line)
        except ValueError as e:
            console.error(f"Parsing error: {e}")
            return

        if not parts:
            return

        from lib.arguments import ArgumentParser

        parser = ArgumentParser()
        parser.parse(parts)

        commands = self.command_loader.load_commands()
        # Плюс встроенные
        try:
            from lib.commands import BUILTIN_COMMANDS

            for name, info in BUILTIN_COMMANDS.items():
                commands.setdefault(name, info)
        except Exception:
            pass

        cmd_name = parser.command
        if cmd_name not in commands:
            console.error(f"The command '{cmd_name}' was not found. Use :list")
            return

        cmd_info = commands[cmd_name]

        # Ленивый queue — как в homer
        from lib.queue import Dispatcher, QueueStorage

        _storage = None
        _dispatcher = None

        class _LazyQueue:
            def _get(self):
                nonlocal _storage, _dispatcher
                if _dispatcher is None:
                    _storage = QueueStorage(self_config)
                    _dispatcher = Dispatcher(
                        _storage,
                        config=self_config,
                        triggered_by=f"shell:{cmd_name}",
                    )
                return _dispatcher

            def __getattr__(self, name):
                return getattr(self._get(), name)

        self_config = self.config

        cmd_context = {
            'config': self.config,
            'logger': self.homer_context['logger'],
            'args': parser.options,
            'root_dir': self.homer_context['root_dir'],
            'command_name': cmd_name,
            'commands': commands,
            'queue': _LazyQueue(),
        }

        try:
            console.info(f"Launch: {console.bold(cmd_name)}")
            result = cmd_info['execute'](cmd_context)
            if result:
                console.warning(f"The command is completed with code {result}")
            else:
                console.success("The command has been completed successfully.")
        except KeyboardInterrupt:
            console.warning("Interrupted by the user")
        except Exception as e:
            console.error(f"Execution error: {e}")
            traceback.print_exc()

    # ─────────────────── Перехват ввода ───────────────────

    def runsource(self, source, filename="<input>", symbol="single"):
        stripped = source.strip()

        # Специальные команды с префиксом :
        if stripped.startswith(':'):
            self._handle_special(stripped)
            return False

        # Прямой ввод команды Homer (однострочный, без "=" и ":")
        if (
            stripped
            and not stripped.startswith(
                (
                    'import',
                    'from',
                    'def ',
                    'class ',
                    'for ',
                    'if ',
                    'while ',
                    'with ',
                    'try',
                    '@',
                    '#',
                    'print(',
                )
            )
            and '=' not in stripped
            and not stripped.endswith(':')
        ):
            first = stripped.split(maxsplit=1)[0]
            known = self.command_loader.load_commands()
            try:
                from lib.commands import BUILTIN_COMMANDS

                for name in BUILTIN_COMMANDS:
                    known.setdefault(name, {})
            except Exception:
                pass

            # Совпадение: точное имя или пространство имён
            if first in known or (
                ':' in first and first.split(':')[0] in {n.split(':')[0] for n in known}
            ):
                self.run_command(stripped)
                return False

        return super().runsource(source, filename, symbol)

    # ─────────────────── Специальные команды ───────────────────

    def _handle_special(self, line):
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ''
        arg = parts[1] if len(parts) > 1 else ''

        if cmd in ('exit', 'quit', 'q'):
            console.comment("Bye!")
            raise SystemExit(0)

        if cmd in ('help', 'h', '?'):
            self._print_help()

        elif cmd in ('list', 'ls'):
            self._print_commands()

        elif cmd in ('run', 'r'):
            if not arg:
                console.error("Usage: :run <command> [arguments]")
            else:
                self.run_command(arg)

        elif cmd == 'reload':
            self.config.load()
            console.success("The config has been reloaded.")

        elif cmd in ('ctx', 'context'):
            console.key_value('config', self.config.config_path)
            console.key_value('root_dir', self.homer_context['root_dir'])
            console.key_value('logger', 'активен')

        elif cmd == 'clear':
            print('\033[2J\033[H', end='')

        else:
            console.error(f"Unknown command: :{cmd}. Enter :help")

    def _print_help(self):
        console.banner("Homer Shell", "interactive mode", color=Color.BRIGHT_MAGENTA)
        console.section("Special commands")
        console.list_item(':help', 'help')
        console.list_item(':list', 'command list')
        console.list_item(':run <cmd> [args]', 'Execute the Homer command.')
        console.list_item(':reload', 'reread config.yml')
        console.list_item(':ctx', 'show the current context')
        console.list_item(':clear', 'clear the screen')
        console.list_item(':exit / :quit', 'exit')
        console.newline()
        console.section("Python mode")
        console.comment("  Available: config, console, logger, Color, commands, ctx, root_dir")
        console.comment("  Example: print(config.get('app.name'))")
        console.newline()
        console.section("Homer teams")
        console.comment("  Можно вводить напрямую, например:")
        console.comment("    idm --user=admin --ver=16")
        console.comment("  or via a prefix :run")
        console.newline()

    def _print_commands(self):
        commands = self.command_loader.load_commands()
        try:
            from lib.commands import BUILTIN_COMMANDS

            for name, info in BUILTIN_COMMANDS.items():
                commands.setdefault(name, info)
        except Exception:
            pass

        if not commands:
            console.warning("There are no available commands.")
            return

        rows = []
        for name, info in sorted(commands.items()):
            rows.append([name, info.get('description', '—')])

        console.table(
            headers=['Command', 'Description'],
            rows=rows,
            align=['l', 'l'],
        )

    # ─────────────────── Запуск ───────────────────

    def interact(self, banner=None):
        console.banner("Homer Shell", "Enter :help for help, :exit to exit")

        try:
            super().interact(banner='', exitmsg='')
        except SystemExit:
            pass
        except KeyboardInterrupt:
            console.newline()
            console.comment("Interrupted (Ctrl+C). Enter :exit to exit.")
