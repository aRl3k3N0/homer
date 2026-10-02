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
        from lib.i18n import get_i18n
        from lib.metrics import get_metrics

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
