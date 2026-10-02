"""
Path resolution for Homer.

All project paths are resolved through this module, so the codebase
never hard-codes 'commands', 'plugins', 'var/cache' etc. Every path
can be overridden in config.yml under the `paths:` section.

Resolution rules
----------------
1. If a value is absolute -- use as-is.
2. If it starts with ~ -- expand home directory.
3. Otherwise -- treat as relative to `paths.base` (which itself
   defaults to the directory containing config.yml).

Environment overrides
---------------------
HOMER_CONFIG            Path to config.yml  (handled in homer entrypoint)
HOMER_BASE_DIR          Overrides paths.base (highest priority)
HOMER_COMMANDS_DIR      Overrides paths.commands_dir
HOMER_PLUGINS_DIR       Overrides paths.plugins_dir
HOMER_EMAIL_DIR         Overrides paths.email_templates_dir
HOMER_LOG_DIR           Overrides paths.log_dir
HOMER_CACHE_DIR         Overrides paths.cache_dir
HOMER_RUN_DIR           Overrides paths.run_dir

Environment variables win over config.yml values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────
#  Defaults (used when config has no `paths:` section)
# ─────────────────────────────────────────────────────────────

DEFAULTS = {
    "base": None,                    # None means "directory of config.yml"
    "run_dir": "var/run",
    "cache_dir": "var/cache",
    "log_dir": "var/log",
    "email_out_dir": "var/email",
    "commands_dir": "commands",
    "plugins_dir": "plugins",
    "email_templates_dir": "email",
    "langs_dir": "langs",
    "templates_dir": "templates",
    "static_dir": "static",
}


# ─────────────────────────────────────────────────────────────
#  Environment overrides for specific paths
# ─────────────────────────────────────────────────────────────

ENV_OVERRIDES = {
    "base": "HOMER_BASE_DIR",
    "run_dir": "HOMER_RUN_DIR",
    "cache_dir": "HOMER_CACHE_DIR",
    "log_dir": "HOMER_LOG_DIR",
    "email_out_dir": "HOMER_EMAIL_OUT_DIR",
    "commands_dir": "HOMER_COMMANDS_DIR",
    "plugins_dir": "HOMER_PLUGINS_DIR",
    "email_templates_dir": "HOMER_EMAIL_DIR",
    "langs_dir": "HOMER_LANGS_DIR",
    "templates_dir": "HOMER_TEMPLATES_DIR",
    "static_dir": "HOMER_STATIC_DIR",
}


# ─────────────────────────────────────────────────────────────
#  Resolution
# ─────────────────────────────────────────────────────────────

def _expand(value: str) -> str:
    """Expand ~ and environment variables in a path string."""
    return os.path.expanduser(os.path.expandvars(value))


def _resolve(base: Path, value: str) -> Path:
    """Resolve a value against base if it is not absolute."""
    value = _expand(value)
    p = Path(value)
    return p if p.is_absolute() else (base / p)


@dataclass(frozen=True)
class Paths:
    """
    Immutable resolved set of paths for a project.

    Construct via Paths.from_config(config, config_path).
    """
    base: Path
    run_dir: Path
    cache_dir: Path
    log_dir: Path
    email_out_dir: Path

    commands_dir: Path
    plugins_dir: Path
    email_templates_dir: Path
    langs_dir: Path
    templates_dir: Path
    static_dir: Path

    # Config file itself
    config_path: Path

    @classmethod
    def from_config(cls, config, config_path: Path) -> "Paths":
        """
        Build a Paths instance from a Config object plus the path to
        the config file that was loaded.

        Priority for each value:
            env var  >  config.yml  >  default
        """
        config_path = Path(config_path).resolve()

        # 1. base
        env_base = os.environ.get(ENV_OVERRIDES["base"])
        if env_base:
            base = Path(_expand(env_base)).resolve()
        else:
            cfg_base = config.get("paths.base")
            if cfg_base:
                base = Path(_expand(cfg_base)).resolve()
            else:
                base = config_path.parent

        # 2. the rest
        def get_path(key: str) -> Path:
            env_name = ENV_OVERRIDES.get(key)
            env_value = os.environ.get(env_name) if env_name else None
            if env_value:
                return Path(_expand(env_value)).resolve()

            cfg_value = config.get(f"paths.{key}")
            if cfg_value is None:
                cfg_value = DEFAULTS[key]

            if cfg_value is None:
                # Only for `base`, which is already handled
                return base

            return _resolve(base, cfg_value)

        return cls(
            base=base,
            run_dir=get_path("run_dir"),
            cache_dir=get_path("cache_dir"),
            log_dir=get_path("log_dir"),
            email_out_dir=get_path("email_out_dir"),
            commands_dir=get_path("commands_dir"),
            plugins_dir=get_path("plugins_dir"),
            email_templates_dir=get_path("email_templates_dir"),
            langs_dir=get_path("langs_dir"),
            templates_dir=get_path("templates_dir"),
            static_dir=get_path("static_dir"),
            config_path=config_path,
        )

    # ─────────── Utilities ───────────

    def ensure_all(self) -> None:
        """Create every directory that should exist at runtime."""
        for p in (
            self.run_dir,
            self.cache_dir,
            self.log_dir,
            self.email_out_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, str]:
        return {
            "base": str(self.base),
            "run_dir": str(self.run_dir),
            "cache_dir": str(self.cache_dir),
            "log_dir": str(self.log_dir),
            "email_out_dir": str(self.email_out_dir),
            "commands_dir": str(self.commands_dir),
            "plugins_dir": str(self.plugins_dir),
            "email_templates_dir": str(self.email_templates_dir),
            "langs_dir": str(self.langs_dir),
            # "templates_dir": str(self.templates_dir),
            # "static_dir": str(self.static_dir),
        }


# ─────────────────────────────────────────────────────────────
#  Module-level helpers (kept for backward compatibility)
# ─────────────────────────────────────────────────────────────
#
# Older code called lib.paths.run_dir(config, root_dir) etc.
# We keep these signatures working, but they now use the full
# resolver when possible.

def run_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "run_dir")


def cache_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "cache_dir")


def log_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "log_dir")


def email_out_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "email_out_dir")


def commands_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "commands_dir")


def plugins_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "plugins_dir")


def email_templates_dir(config, root_dir: Path) -> Path:
    return _legacy(config, root_dir, "email_templates_dir")


def _legacy(config, root_dir: Path, key: str) -> Path:
    """
    Best-effort legacy resolver. Uses config if a full Paths object
    is not available (e.g. when called early during startup).
    """
    env_name = ENV_OVERRIDES.get(key)
    env_value = os.environ.get(env_name) if env_name else None
    if env_value:
        return Path(_expand(env_value)).resolve()

    base = root_dir
    cfg_base = config.get("paths.base") if config else None
    if cfg_base:
        base = Path(_expand(cfg_base)).resolve()
        if not base.is_absolute():
            base = (root_dir / cfg_base).resolve()

    value = config.get(f"paths.{key}") if config else None
    if value is None:
        value = DEFAULTS[key]

    return _resolve(base, value)


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
