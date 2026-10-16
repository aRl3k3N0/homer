"""
Tests for cluster:status, cluster:gc, cluster:describe.
"""
import pytest


class _Context:
    def __init__(self, config, args=None):
        self.data = {
            "config": config,
            "args": args or {},
            "root_dir": config.get("paths.cache_dir") or ".",
        }

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


def test_status_no_nodes(cluster_config, capsys):
    from homer.commands import cluster
    ctx = _Context(cluster_config)
    rc = cluster.status(ctx)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Homer Cluster" in captured.out


def test_status_with_node(cluster_config, registry, capsys):
    from homer.commands import cluster
    registry.register()
    registry.db.close()
    cluster_config._data = getattr(cluster_config, "_data", {})
    ctx = _Context(cluster_config)
    rc = cluster.status(ctx)
    captured = capsys.readouterr()
    assert rc == 0
    assert "test-node-1" in captured.out or "kraken" in captured.out


def test_describe_missing(cluster_config, capsys):
    from homer.commands import cluster
    ctx = _Context(cluster_config, {"_positional": ["missing-id"]})
    rc = cluster.describe(ctx)
    assert rc == 1


def test_gc_runs(cluster_config, capsys):
    from homer.commands import cluster
    ctx = _Context(cluster_config, {"older": "3600"})
    rc = cluster.gc(ctx)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Removed" in captured.out or "stale" in captured.out
