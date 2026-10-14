"""
Root-level pytest fixtures for Homer.

Fixtures declared here are visible to every test under tests/.
Local conftest.py files can add more (or override) if needed.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests._helpers.cli_runner import make_cli_runner, CLIRunner  # noqa: E402


# ═══════════════════════════════════════════════════════════════
#                    Project / CLI runner
# ═══════════════════════════════════════════════════════════════

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
    Factory to create multiple isolated projects in the same test.
    """
    created = []

    def _make(name: str = "proj", **kwargs) -> CLIRunner:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        runner = make_cli_runner(d, **kwargs)
        created.append(runner)
        return runner

    return _make


# ═══════════════════════════════════════════════════════════════
#                    Config fixture (generic)
# ═══════════════════════════════════════════════════════════════
#
# Used by test_notify.py, test_queue_dispatcher.py,
# test_webui_smoke.py and others.

@pytest.fixture
def tmp_config(tmp_path):
    """
    Real Config object backed by a temp config.yml.

    Storage: SQLite at <tmp>/scheduler.db.
    Logging: CRITICAL (silent).
    WebUI: enabled, minimal.
    Notifications: empty (disabled).
    """
    from lib.config import Config

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        f"""
app:
  name: HomerTest
  version: 0.0.1

logging:
  level: CRITICAL
  console: false

paths:
  base: {tmp_path}
  run_dir: {tmp_path}/run
  cache_dir: {tmp_path}/cache
  log_dir: {tmp_path}/log

scheduler:
  storage: sqlite
  sqlite:
    path: {tmp_path}/scheduler.db
  lease_seconds: 60
  heartbeat_seconds: 5
  max_workers: 2
  interval: 30

webui:
  enabled: true
  host: 127.0.0.1
  port: 0

notifications:
  enabled: []

i18n:
  locale: en
  fallback: en
  missing_log: false
""",
        encoding="utf-8",
    )
    return Config(cfg_path)


# ═══════════════════════════════════════════════════════════════
#                    Queue fixtures
# ═══════════════════════════════════════════════════════════════
#
# Used by test_queue_storage.py, test_queue_dispatcher.py.

@pytest.fixture
def sqlite_storage(tmp_config):
    """
    Fresh QueueStorage backed by SQLite in tmp_config.
    """
    from lib.queue import QueueStorage
    storage = QueueStorage(tmp_config)
    yield storage
    try:
        storage.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#                    Scheduler fixture
# ═══════════════════════════════════════════════════════════════
#
# Used by test_scheduler.py.

@pytest.fixture
def sqlite_scheduler_storage(tmp_config):
    """
    Fresh DBStorage for cron tasks, backed by SQLite in tmp_config.
    """
    from lib.scheduler import create_storage
    storage = create_storage(tmp_config)
    yield storage
    try:
        storage.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#                    Command loader fixture
# ═══════════════════════════════════════════════════════════════
#
# Used by test_command_loader.py.

@pytest.fixture
def sample_command_dir(tmp_path):
    """
    A directory with a couple of ready command files:

        commands/hello.py            -> name "hello"
        commands/report/daily.py     -> name "report:daily"
    """
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "__init__.py").write_text("", encoding="utf-8")

    (commands / "hello.py").write_text(
        'DESCRIPTION = "Привет"\n'
        'def execute(context):\n'
        '    return 0\n',
        encoding="utf-8",
    )

    sub = commands / "report"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "daily.py").write_text(
        'DESCRIPTION = "Ежедневно"\n'
        'def execute(context):\n'
        '    return 0\n',
        encoding="utf-8",
    )

    return commands


# ═══════════════════════════════════════════════════════════════
#                    Cluster test fixtures
# ═══════════════════════════════════════════════════════════════
#
# Declared at root level so that tests outside tests/cluster/
# (e.g. tests/commands/test_cluster.py) can use them.

@pytest.fixture
def cluster_config(tmp_path):
    """
    Config-like object with .get('a.b.c') dotted access and .paths.

    Backed by a temp SQLite file so NodeRegistry / ClusterFiles can
    use it directly.
    """
    class _Config(dict):
        def get(self, key, default=None):
            cur = self
            for part in key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return default
            return cur

        @property
        def paths(self):
            return None

    db_path = tmp_path / "test.db"
    return _Config({
        "app": {"version": "1.0.0"},
        "scheduler": {
            "storage": "sqlite",
            "sqlite": {"path": str(db_path)},
        },
        "paths": {
            "run_dir": str(tmp_path / "run"),
            "cache_dir": str(tmp_path / "cache"),
            "log_dir": str(tmp_path / "log"),
            "commands_dir": str(tmp_path / "commands"),
            "plugins_dir": str(tmp_path / "plugins"),
            "langs_dir": str(tmp_path / "langs"),
            "templates_dir": str(tmp_path / "templates"),
            "static_dir": str(tmp_path / "static"),
            "email_templates_dir": str(tmp_path / "email"),
        },
        "cluster": {
            "enabled": True,
            "ttl_seconds": 60,
            "heartbeat_seconds": 5,
            "lease_seconds": 30,
        },
    })


@pytest.fixture
def registry(cluster_config):
    """
    Fresh NodeRegistry pointing at the cluster_config SQLite file.
    """
    from lib.cluster.nodes import NodeRegistry
    reg = NodeRegistry(
        cluster_config,
        node_id="test-node-1",
        role="worker",
        heartbeat_interval=1,
        ttl_seconds=60,
    )
    yield reg
    try:
        reg.stop_heartbeat()
    except Exception:
        pass
    try:
        reg.db.close()
    except Exception:
        pass
