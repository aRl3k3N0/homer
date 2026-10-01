"""
Парсер аргументов командной строки
"""
import re


class ArgumentParser:
    def __init__(self):
        self.command = None
        self.options = {}
        self.flags = set()

    def parse(self, args):
        if not args:
            return
        self.command = args[0]
        for arg in args[1:]:
            if arg.startswith('--'):
                if '=' in arg:
                    key, value = arg[2:].split('=', 1)
                    self.options[key] = self._parse_value(value)
                else:
                    self.flags.add(arg[2:])
                    self.options[arg[2:]] = True
            elif arg.startswith('-') and len(arg) > 1:
                if '=' in arg:
                    key, value = arg[1:].split('=', 1)
                    self.options[key] = self._parse_value(value)
                else:
                    self.flags.add(arg[1:])
                    self.options[arg[1:]] = True
            else:
                self.options.setdefault('_positional', []).append(arg)

    def _parse_value(self, value):
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False
        if re.match(r'^-?\d+$', value):
            return int(value)
        if re.match(r'^-?\d+\.\d+$', value):
            return float(value)
        return value

    def get(self, key, default=None):
        return self.options.get(key, default)

    def has(self, key):
        return key in self.options