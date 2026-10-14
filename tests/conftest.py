"""
Root-level pytest fixtures for Homer.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests._helpers.cli_runner import make_cli_runner, CLIRunner  # noqa: E402


@pytest.fixture
def cli_runner(tmp_path) -> CLIRunner:
    """
    Isolated project + `homer` CLI runner.
    Usage:
        r = cli_runner("cluster:status")
        assert r.ok()
    """
    return make_cli_runner(tmp_path)


@pytest.fixture
def cli_runner_factory(tmp_path):
    """
    Factory for multiple projects in the same test.
    """
    created = []

    def _make(name: str = "proj", **kwargs) -> CLIRunner:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        runner = make_cli_runner(d, **kwargs)
        created.append(runner)
        return runner

    return _make
