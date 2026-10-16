"""
Запуск standalone Prometheus exporter.
"""
DESCRIPTION = "To run Prometheus metrics server"


def execute(context):
    from homer.metrics import setup_metrics_server, get_metrics
    from homer.queue import QueueStorage
    import time

    args = context['args']
    port = int(args.get('port', 9101))
    addr = args.get('addr', '0.0.0.0')

    get_metrics()  # инициализация
    setup_metrics_server(port=port, addr=addr)

    # Периодически обновляем gauge queue_jobs_in_progress
    storage = QueueStorage(context['config'])
    m = get_metrics()
    try:
        while True:
            try:
                s = storage.stats()
                m.jobs_in_progress.set(s.get('running', 0))
            except Exception:
                pass
            time.sleep(5)
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        storage.close()
