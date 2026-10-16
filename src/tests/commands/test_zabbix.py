"""
Tests for the Zabbix metric command.
"""
import json

import pytest


class _Context:
    def __init__(self, config, args=None):
        self.data = {"config": config, "args": args or {}}

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)


@pytest.fixture
def ctx(cluster_config):
    return _Context(cluster_config)


def test_metric_unknown_key(ctx, capsys):
    from homer.commands import zabbix
    ctx.data["args"] = {"_positional": ["nope.nope"]}
    rc = zabbix.metric(ctx)
    assert rc == 1


def test_metric_ws_subscribers(ctx):
    from homer.commands import zabbix
    ctx.data["args"] = {"_positional": ["ws.subscribers"]}
    rc = zabbix.metric(ctx)
    assert rc == 0


def test_metric_queue_pending(ctx, capsys):
    from homer.commands import zabbix
    ctx.data["args"] = {"_positional": ["queue.pending"]}
    rc = zabbix.metric(ctx)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip().isdigit()


def test_metric_nodes_total(ctx, capsys):
    from homer.commands import zabbix
    ctx.data["args"] = {"_positional": ["nodes.total"]}
    rc = zabbix.metric(ctx)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip().isdigit()


def test_discover_returns_json(ctx, capsys):
    from homer.commands import zabbix
    rc = zabbix.discover(ctx)
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert "data" in data
    assert any(item["{#HOMER_METRIC}"] == "queue.pending"
               for item in data["data"])


def test_metric_without_key_returns_error(ctx):
    from homer.commands import zabbix
    ctx.data["args"] = {}
    rc = zabbix.metric(ctx)
    assert rc == 1
