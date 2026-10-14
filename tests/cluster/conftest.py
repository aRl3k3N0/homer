"""
Fixtures for cluster tests.
"""
import pytest


@pytest.fixture
def cluster_config(tmp_path):
    """Config-like object with a minimal .get() interface."""
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
    """Fresh NodeRegistry pointing at a temp SQLite file."""
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
