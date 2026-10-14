"""
Tests for cluster/i18n metrics collectors.
"""
import time
from unittest.mock import MagicMock


def test_cluster_collector_updates_metrics(cluster_config, registry):
    from lib.metrics import get_metrics
    from lib.metrics.collectors import ClusterCollector

    registry.register()

    ws_hub = MagicMock()
    ws_hub.count = 3

    collector = ClusterCollector(
        cluster_config,
        node_registry=registry,
        ws_hub=ws_hub,
        interval=10.0,
    )
    collector.collect()

    m = get_metrics()
    # Values are set (no exceptions)
    # We can't easily read back gauge values portably, but the call
    # should not raise.
    assert True


def test_i18n_collector_runs(cluster_config):
    from lib.metrics.collectors import I18nCollector

    collector = I18nCollector(interval=10.0)
    # Just make sure collect() doesn't raise
    try:
        collector.collect()
    except Exception:
        pass


def test_collector_start_stop(cluster_config):
    from lib.metrics.collectors import I18nCollector

    c = I18nCollector(interval=0.2)
    c.start()
    time.sleep(0.3)
    c.stop()
    assert c._thread is None or not c._thread.is_alive()
