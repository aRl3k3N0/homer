"""
Сборщики метрик, которые дёргаются по таймеру или перед /metrics.
"""
import threading
import time


class I18nCollector:
    def __init__(self, interval: float = 15.0):
        self.interval = interval
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='homer-metrics-i18n',
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def collect(self):
        from homer.i18n import get_i18n
        from homer.metrics import get_metrics

        i18n = get_i18n()
        m = get_metrics()

        stats = i18n.cache_stats()
        # Gauge — абсолютные значения
        m.i18n_cache_size.set(stats['size'])
        m.i18n_missing_keys.set(len(i18n.missing_keys()))
        m.i18n_locales.set(len(i18n.available_locales()))

        # Counter — только инкремент. Храним предыдущее значение
        last_hits = getattr(self, '_last_hits', 0)
        last_misses = getattr(self, '_last_misses', 0)
        if stats['hits'] > last_hits:
            m.i18n_cache_hits.inc(stats['hits'] - last_hits)
        if stats['misses'] > last_misses:
            m.i18n_cache_misses.inc(stats['misses'] - last_misses)
        self._last_hits = stats['hits']
        self._last_misses = stats['misses']

        # По локалям
        for loc in i18n.available_locales():
            keys = i18n.keys_for(loc)
            m.i18n_translations.labels(locale=loc).set(len(keys))

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.collect()
            except Exception:
                pass


class ClusterCollector:
    """
    Polls node registry, WS hub, and cluster files every N seconds
    and updates Prometheus gauges.
    """

    def __init__(self, config, node_registry=None, ws_hub=None,
                 cluster_files=None, interval: float = 15.0):
        self.config = config
        self.node_registry = node_registry
        self.ws_hub = ws_hub
        self.cluster_files = cluster_files
        self.interval = interval
        from typing import Optional
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="homer-metrics-cluster", daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def collect(self):
        from homer.metrics import get_metrics

        m = get_metrics()

        # ─── Nodes by role ───
        if self.node_registry is not None:
            try:
                nodes = self.node_registry.list_nodes(only_alive=True)
                roles = {"primary": 0, "worker": 0, "read-only": 0}
                for n in nodes:
                    roles[n.role] = roles.get(n.role, 0) + 1
                for role, count in roles.items():
                    m.cluster_nodes.labels(role=role).set(count)
            except Exception:
                pass

        # ─── WS subscribers ───
        if self.ws_hub is not None:
            try:
                m.cluster_ws_subscribers.set(self.ws_hub.count)
            except Exception:
                pass

        # ─── Local role ───
        if self.node_registry is not None:
            try:
                my_role = self.node_registry.role
                for role in ("primary", "worker", "read-only"):
                    m.cluster_role.labels(role=role).set(
                        1 if role == my_role else 0
                    )
            except Exception:
                pass

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.collect()
            except Exception:
                pass


class I18nCollector:
    """
    (Optional) Collects i18n cache statistics.
    """

    def __init__(self, interval: float = 15.0):
        self.interval = interval
        from typing import Optional
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="homer-metrics-i18n", daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def collect(self):
        from homer.i18n import get_i18n
        from homer.metrics import get_metrics

        i18n = get_i18n()
        m = get_metrics()
        try:
            stats = i18n.cache_stats()
            if hasattr(m, "i18n_cache_size"):
                m.i18n_cache_size.set(stats.get("size", 0))
        except Exception:
            pass

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.collect()
            except Exception:
                pass
