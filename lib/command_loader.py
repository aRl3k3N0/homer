"""
Загрузчик команд из директории.
"""
import importlib.util
from pathlib import Path


class CommandLoader:
    def __init__(self, commands_dir):
        self.commands_dir = Path(commands_dir)
        self.plugin_dirs: list[tuple[str, Path]] = []

    def add_plugin_commands(self, plugin_name: str, plugin_commands_dir: Path):
        """
        Регистрирует команды плагина. Команды получат имя
        '<plugin_name>:<local_name>'.
        """
        self.plugin_dirs.append((plugin_name, plugin_commands_dir))

    def load_commands(self):
        commands = {}

        # Ядро
        if self.commands_dir.exists():
            for py in self.commands_dir.rglob('*.py'):
                if py.name == '__init__.py':
                    continue
                name = self._get_command_name(py)
                if not name:
                    continue
                info = self._load_command(py, name)
                if info:
                    info['source'] = 'user'
                    commands[name] = info

        # Плагины
        for plugin_name, pdir in self.plugin_dirs:
            if not pdir.exists():
                continue
            for py in pdir.rglob('*.py'):
                if py.name == '__init__.py':
                    continue
                local = self._get_command_name_from(py, pdir)
                if not local:
                    continue
                full = f"{plugin_name}:{local}"
                info = self._load_command(py, full)
                if info:
                    info['source'] = f'plugin:{plugin_name}'
                    commands[full] = info

        return commands

    def _get_command_name_from(self, py_file: Path, base: Path) -> str:
        rel = py_file.relative_to(base)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace('.py', '')
        if parts[-1] == 'main':
            parts = parts[:-1]
            if not parts:
                return None
        return ':'.join(parts)

    def _get_command_name(self, py_file):
        rel_path = py_file.relative_to(self.commands_dir)
        parts = list(rel_path.parts)
        parts[-1] = parts[-1].replace('.py', '')
        if parts[-1] == 'main':
            parts = parts[:-1]
            if not parts:
                return None
        return ':'.join(parts)

    def _load_command(self, py_file, command_name):
        try:
            spec = importlib.util.spec_from_file_location(
                f"commands.{command_name.replace(':', '.')}",
                py_file,
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, 'execute'):
                print(f"⚠️  Команда {command_name} не имеет функции execute()")
                return None

            description = getattr(module, 'DESCRIPTION',
                                  getattr(module, '__doc__', 'Нет описания'))
            if description:
                description = description.strip().split('\n')[0]

            return {
                'execute': module.execute,
                'description': description,
                'module': module,
                'path': py_file,
            }
        except Exception as e:
            print(f"⚠️  Ошибка загрузки команды {command_name}: {e}")
            return None
