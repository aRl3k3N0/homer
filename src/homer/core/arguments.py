"""
Command line argument parser with global options support.

Global options (extracted before command parsing):
    --lang=ru            preferred language for this invocation
    --config=path.yml    path to config.yml
    --no-cache           disable registry/config caches (useful for debug)
    --verbose            verbose output

Global options can appear anywhere: before or after the command and
its own arguments. They are removed from the argv passed to the
command-specific parser.
"""

from __future__ import annotations

import re
from typing import Any, Optional


GLOBAL_OPTIONS = {
    "lang",          # str
    "config",        # str
    "no-cache",      # bool (flag)
    "verbose",       # bool (flag)
}


class ArgumentParser:
    def __init__(self):
        self.command: Optional[str] = None
        self.options: dict[str, Any] = {}
        self.flags: set[str] = set()

    def parse(self, args: list[str]) -> None:
        if not args:
            return
        self.command = args[0]
        for arg in args[1:]:
            self._parse_one(arg)

    def _parse_one(self, arg: str) -> None:
        if arg.startswith("--"):
            if "=" in arg:
                key, value = arg[2:].split("=", 1)
                self.options[key] = self._parse_value(value)
            else:
                self.flags.add(arg[2:])
                self.options[arg[2:]] = True
        elif arg.startswith("-") and len(arg) > 1:
            if "=" in arg:
                key, value = arg[1:].split("=", 1)
                self.options[key] = self._parse_value(value)
            else:
                self.flags.add(arg[1:])
                self.options[arg[1:]] = True
        else:
            self.options.setdefault("_positional", []).append(arg)

    @staticmethod
    def _parse_value(value: str) -> Any:
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        if re.match(r"^-?\d+$", value):
            return int(value)
        if re.match(r"^-?\d+\.\d+$", value):
            return float(value)
        return value

    def get(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.options


# ─────────────────────────────────────────────────────────────
#  Global options extraction
# ─────────────────────────────────────────────────────────────

class GlobalOptions:
    def __init__(self):
        self.lang: Optional[str] = None
        self.config: Optional[str] = None
        self.no_cache: bool = False
        self.verbose: bool = False

    def __repr__(self) -> str:
        return (f"GlobalOptions(lang={self.lang!r}, config={self.config!r}, "
                f"no_cache={self.no_cache}, verbose={self.verbose})")


def extract_globals(argv: list[str]) -> tuple[GlobalOptions, list[str]]:
    """
    Split argv into (global_options, remaining_args).

    Understands:
        --lang=ru       --config=path       --no-cache      --verbose
        --lang ru       --config path       -v
    """
    g = GlobalOptions()
    rest: list[str] = []
    i = 0

    while i < len(argv):
        arg = argv[i]

        # --key=value form
        if arg.startswith("--") and "=" in arg:
            key, value = arg[2:].split("=", 1)
            if key == "lang":
                g.lang = value
                i += 1
                continue
            if key == "config":
                g.config = value
                i += 1
                continue
            rest.append(arg)
            i += 1
            continue

        # --key value form
        if arg in ("--lang", "--config"):
            if i + 1 >= len(argv):
                raise SystemExit(f'Global option {arg} requires a value')
            value = argv[i + 1]
            if arg == "--lang":
                g.lang = value
            else:
                g.config = value
            i += 2
            continue

        # Flags
        if arg == "--no-cache":
            g.no_cache = True
            i += 1
            continue
        if arg in ("--verbose", "-v"):
            g.verbose = True
            i += 1
            continue

        rest.append(arg)
        i += 1

    return g, rest
