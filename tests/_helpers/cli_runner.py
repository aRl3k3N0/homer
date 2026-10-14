"""
Subprocess runner for the `homer` CLI.

Creates an isolated project directory with its own config.yml, runs
`homer <args>` there, and captures stdout/stderr/exit code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
HOMER_BIN = REPO_ROOT / "homer"


@dataclass
class CLIResult:
    returncode: int
    stdout: str
    stderr: str
    project_dir: Path

    def ok(self) -> bool:
        return self.returncode == 0

    def combined(self) -> str:
        return self.stdout + "\n" + self.stderr

    def __repr__(self):
        return (f"<CLIResult rc={self.returncode} "
                f"stdout={self.stdout[:120]!r} stderr={self.stderr[:120]!r}>")


class CLIRunner:
    """
    Helper around `subprocess.run([sys.executable, homer, ...])`.

    Usage:
        r = cli("cluster:status")
        assert r.ok()
        assert "Homer Cluster" in r.stdout
    """

    def __init__(self, project_dir: Path, timeout: float = 30.0):
        self.project_dir = Path(project_dir)
        self.timeout = timeout

    def __call__(self, args: Iterable[str], *,
                 env: Optional[dict] = None,
                 input_text: Optional[str] = None,
                 timeout: Optional[float] = None) -> CLIResult:
        if isinstance(args, str):
            args = args.split()
        cmd = [sys.executable, str(HOMER_BIN)] + list(args)

        full_env = os.environ.copy()
        full_env["HOMER_CONFIG"] = str(self.project_dir / "config.yml")
        full_env["PYTHONPATH"] = str(REPO_ROOT)
        full_env["PYTHONDONTWRITEBYTECODE"] = "1"
        if env:
            full_env.update(env)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                env=full_env,
                input=input_text,
            )
        except subprocess.TimeoutExpired as e:
            return CLIResult(
                returncode=124,
                stdout=e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                stderr=(f"TIMEOUT after {timeout or self.timeout}s\n"
                        + (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""))),
                project_dir=self.project_dir,
            )

        return CLIResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            project_dir=self.project_dir,
        )


def _write_default_config(project_dir: Path, *, extra_yaml: str = "") -> None:
    """
    Minimal working config.yml for an isolated project.

    Uses SQLite in <project_dir>/var/cache/homer.db. Registers `commands/`
    and `plugins/` directories empty; log/run/cache dirs auto-created.
    """
    cfg = project_dir / "config.yml"
    cfg.write_text(textwrap.dedent(f"""
        app:
          name: HomerTest
          version: 1.0.0

        paths:
          base: {project_dir}
          run_dir: var/run
          cache_dir: var/cache
          log_dir: var/log

        logging:
          level: WARNING
          console: false

        scheduler:
          storage: sqlite
          sqlite:
            path: var/cache/homer.db
          lease_seconds: 10
          heartbeat_seconds: 5
          interval: 5
          max_workers: 1

        i18n:
          locale: en
          fallback: en
          missing_log: false

        cluster:
          enabled: true
          role: worker
          ttl_seconds: 60
          heartbeat_seconds: 5
          election_enabled: false

        webui:
          enabled: true
          host: 127.0.0.1
          port: 0
        {extra_yaml}
    """).strip() + "\n", encoding="utf-8")

    (project_dir / "commands").mkdir(exist_ok=True)
    (project_dir / "commands" / "__init__.py").write_text("", encoding="utf-8")
    (project_dir / "plugins").mkdir(exist_ok=True)
    (project_dir / "var").mkdir(exist_ok=True)
    (project_dir / "var" / "cache").mkdir(exist_ok=True)
    (project_dir / "var" / "run").mkdir(exist_ok=True)
    (project_dir / "var" / "log").mkdir(exist_ok=True)


def make_cli_runner(tmp_path: Path, *,
                    extra_yaml: str = "",
                    copy_commands_from: Optional[Path] = None) -> CLIRunner:
    """
    Build a CLI runner in an isolated temp project.
    """
    project = tmp_path / "homer_project"
    project.mkdir(parents=True, exist_ok=True)
    _write_default_config(project, extra_yaml=extra_yaml)

    if copy_commands_from and copy_commands_from.exists():
        dst = project / "commands"
        shutil.copytree(copy_commands_from, dst, dirs_exist_ok=True)

    return CLIRunner(project)
