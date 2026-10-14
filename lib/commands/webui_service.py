"""
Внутренние и публичные команды управления Web UI.

Публичные:
    webui:start    — запустить в фоне (PID в var/run/webui.pid)
    webui:stop     — остановить
    webui:restart  — перезапустить
    webui:reload   — SIGHUP: перечитать конфиг
    webui:status   — статус
    webui:logs     — хвост лога
    webui:tail     — tail -f лога
    webui:url      — печатать URL
    webui:workers  — счётчики воркеров
    webui:reset-auth — сбросить пароль админа

Внутренняя:
    _webui_run     — сам процесс сервера (не вызывайте вручную)
"""
import os
import sys
from pathlib import Path

from lib.console import console, Color
from lib.daemon import ServiceManager, ServiceStatus


DESCRIPTIONS = {
    'start':      "Запустить Web UI в фоне (как pg_ctl)",
    'stop':       "Остановить Web UI",
    'restart':    "Перезапустить Web UI",
    'reload':     "Перечитать конфиг Web UI (SIGHUP)",
    'status':     "Статус Web UI",
    'logs':       "Показать хвост лога Web UI",
    'tail':       "Следить за логом Web UI (tail -f)",
    'url':        "Печатать URL Web UI (для скриптов)",
    'workers':    "Счётчики воркеров очереди",
    'reset-auth': "Сбросить пароль администратора",
}


# ─────────── Helpers ───────────

def _manager(context) -> ServiceManager:
    return ServiceManager(
        Path(context['root_dir']),
        'webui',
        config=context.get('config'),
    )


def _homer_argv(context) -> list[str]:
    """Полная команда запуска внутреннего процесса."""
    root = Path(context['root_dir'])
    homer = root / 'homer'
    argv = [sys.executable, str(homer), '_webui_run']

    args = context['args']
    if args.get('host'):
        argv.append(f"--host={args['host']}")
    if args.get('port'):
        argv.append(f"--port={args['port']}")
    if args.get('workers'):
        argv.append(f"--workers={args['workers']}")
    return argv


def _apply_cluster_json(config, root_dir):
    """
    If var/cluster.json exists (created by `homer cluster:join`),
    use it to fill missing cluster.* config values.
    """
    import json
    from pathlib import Path
    p = Path(root_dir) / "var" / "cluster.json"
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return
    cluster = config._data.setdefault("cluster", {})
    if not cluster.get("node_id") and data.get("node_id"):
        cluster["node_id"] = data["node_id"]
    if not cluster.get("primary_ws_url") and data.get("ws_url"):
        cluster["primary_ws_url"] = data["ws_url"]
    if not cluster.get("ws_token") and data.get("ws_token"):
        cluster["ws_token"] = data["ws_token"]
    if not cluster.get("role") and data.get("role"):
        cluster["role"] = data["role"]


# ─────────── Публичные команды ───────────

def start(context):
    mgr = _manager(context)
    st = mgr.status()

    if st.status == ServiceStatus.RUNNING:
        console.warning(f"Web UI уже запущен (pid {st.pid})")
        console.comment(f"Лог: {st.log_file}")
        return 0

    if st.status == ServiceStatus.STALE:
        console.comment("Обнаружен stale PID — очищаю")
        mgr.stop()

    argv = _homer_argv(context)
    try:
        st = mgr.start(argv)
    except Exception as e:
        console.error(f"Не удалось запустить: {e}")
        return 1

    if st.status == ServiceStatus.RUNNING:
        console.success(f"Web UI запущен (pid {st.pid})")
        console.key_value('Лог', str(st.log_file))
        console.key_value('PID-файл', str(st.pid_file))
        _print_access_hint(context)
        return 0

    console.error(f"Не удалось запустить (статус: {st.status})")
    if st.log_file and st.log_file.exists():
        console.comment(f"Проверьте {st.log_file}")
    return 1


def stop(context):
    mgr = _manager(context)
    st = mgr.status()

    if st.status == ServiceStatus.STOPPED:
        console.comment("Web UI не запущен")
        return 0

    if st.status == ServiceStatus.STALE:
        console.comment("Убираю stale PID-файл")
        mgr.stop()
        return 0

    console.info(f"Останавливаю (pid {st.pid})…")
    st = mgr.stop()
    console.success("Web UI остановлен")
    return 0


def restart(context):
    mgr = _manager(context)
    argv = _homer_argv(context)

    st = mgr.status()
    if st.status == ServiceStatus.RUNNING:
        console.info(f"Останавливаю (pid {st.pid})…")
        mgr.stop()
        import time
        time.sleep(0.5)

    try:
        st = mgr.start(argv, force=True)
    except Exception as e:
        console.error(f"Не удалось запустить: {e}")
        return 1

    if st.status == ServiceStatus.RUNNING:
        console.success(f"Web UI перезапущен (pid {st.pid})")
        _print_access_hint(context)
        return 0
    console.error("Не удалось перезапустить")
    return 1


def reload(context):
    mgr = _manager(context)
    st = mgr.status()

    if st.status != ServiceStatus.RUNNING:
        console.error("Web UI не запущен")
        return 1

    st = mgr.reload()
    console.success(f"SIGHUP отправлен процессу {st.pid}")
    console.comment("Проверьте лог, чтобы убедиться, что конфиг перечитан")
    return 0


def _http_healthcheck(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)


def status(context):
    mgr = _manager(context)
    st = mgr.status()

    status_color = {
        ServiceStatus.RUNNING:  Color.BRIGHT_GREEN,
        ServiceStatus.STOPPED:  Color.BRIGHT_BLACK,
        ServiceStatus.STALE:    Color.BRIGHT_YELLOW,
        ServiceStatus.UNKNOWN:  Color.WHITE,
    }.get(st.status, Color.WHITE)

    console.banner(f"Web UI", st.status, color=status_color)

    console.key_value('Статус', console.colored(st.status, status_color))
    if st.pid:
        console.key_value('PID', st.pid)
    if st.started_at:
        console.key_value('Запущен', st.started_at.strftime('%Y-%m-%d %H:%M:%S'))
    if st.uptime:
        console.key_value('Uptime', _fmt_uptime(st.uptime))
    if st.message:
        console.key_value('Комментарий', st.message)
    console.key_value('PID-файл', str(st.pid_file))
    console.key_value('Лог', str(st.log_file))

    if st.status == ServiceStatus.RUNNING:
        cfg = context['config']
        host = cfg.get('webui.host', '127.0.0.1')
        port = cfg.get('webui.port', 8080)
        console.key_value('URL', f"http://{host}:{port}/")

    cfg = context['config']
    host = cfg.get('webui.host', '127.0.0.1')
    if cfg.get('webui.ssl.enabled'):
        base = f"https://{host}:{cfg.get('webui.ssl.port', 443)}"
    else:
        base = f"http://{host}:{cfg.get('webui.port', 80)}"
    ok, msg = _http_healthcheck(base + '/healthz')
    console.key_value('Healthcheck', f"{'OK' if ok else 'FAIL'} — {msg}")
    return 0


def logs(context):
    mgr = _manager(context)
    st = mgr.status()

    if not st.log_file or not Path(st.log_file).exists():
        console.warning("Лог-файл отсутствует")
        return 0

    n = int(context['args'].get('lines', 50))
    try:
        lines = Path(st.log_file).read_text(
            encoding='utf-8', errors='replace',
        ).splitlines()
    except Exception as e:
        console.error(f"Ошибка чтения лога: {e}")
        return 1

    console.section(f"Хвост лога — {st.log_file.name} ({n} строк)")
    for line in lines[-n:]:
        print(line)
    return 0


def tail(context):
    """Постоянный follow лога. Ctrl+C для выхода."""
    import time
    from lib.paths import log_dir

    args = context['args']
    command = args.get('command') or 'webui'
    date_ = args.get('date')
    follow = args.get('follow', True) is not False

    from datetime import date as _date
    target_date = date_ or _date.today().isoformat()

    base = log_dir(context['config'], Path(context['root_dir']))
    path = base / command / f"{target_date}.log"

    if not path.exists():
        console.error(f"Файл не найден: {path}")
        return 1

    console.section(f"tail -f {path}")
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    if not follow:
                        break
                    time.sleep(0.3)
                    continue
                print(line.rstrip())
    except KeyboardInterrupt:
        console.newline()
        return 0
    return 0


def url(context):
    """Печатает только URL — для скриптов."""
    cfg = context['config']
    host = cfg.get('webui.host', '127.0.0.1')
    ssl_cfg = cfg.get('webui.ssl', {}) or {}
    if ssl_cfg.get('enabled'):
        scheme = 'https'
        port = int(ssl_cfg.get('port', 443))
    else:
        scheme = 'http'
        port = int(cfg.get('webui.port', 80))
    url_ = f"{scheme}://{host}"
    if (scheme == 'https' and port != 443) or (scheme == 'http' and port != 80):
        url_ += f":{port}"
    print(url_)
    return 0


def workers(context):
    """Счётчики воркеров: running/pending из очереди."""
    from lib.queue import QueueStorage

    cfg = context['config']
    storage = QueueStorage(cfg)
    try:
        stats = storage.stats()
        rows = [
            ['running', stats.get('running', 0)],
            ['pending', stats.get('pending', 0)],
            ['done',    stats.get('done', 0)],
            ['failed',  stats.get('failed', 0)],
        ]
        console.banner("Web UI workers")
        console.table(
            headers=['Статус', 'Задач'],
            rows=rows,
            align=['l', 'r'],
        )
    finally:
        storage.close()
    return 0


def reset_auth(context):
    """Сброс пароля администратора (аварийная операция)."""
    from lib.auth import AuthStore
    store = AuthStore(context['config'])
    try:
        username = context['args'].get('username', 'admin')
        u = store.get_user_by_name(username)
        if u is None:
            uid = store.create_user(username, password='admin', provider='local')
            store.assign_role(uid, 'admin')
            console.success(f"Создан админ '{username}' с паролем 'admin'")
        else:
            store.set_password(username, 'admin')
            store.set_enabled(username, True)
            if 'admin' not in store.roles_for_user(u.id):
                store.assign_role(u.id, 'admin')
            console.success(f"Пароль '{username}' сброшен на 'admin'")
        console.warning("Смените пароль сразу после входа: user:passwd")
        return 0
    finally:
        store.close()


# ─────────── Внутренняя команда: сам процесс ───────────

def _run(context):
    import signal
    import threading
    import uvicorn

    from lib.webui import create_app
    from lib.logger import Logger

    cfg = context['config']
    root = Path(context['root_dir'])
    args = context['args']

    # ─── Cluster config from var/cluster.json ───
    _apply_cluster_json(cfg, root)

    logger = Logger(cfg, root)

    # ─── NodeRegistry + ClusterFiles + Election ───
    node_registry = None
    cluster_files = None
    election = None
    cluster_client = None

    if cfg.get("cluster.enabled", False):
        try:
            from lib.cluster.nodes import NodeRegistry
            from lib.cluster.files import ClusterFiles

            node_registry = NodeRegistry(
                cfg,
                role=cfg.get("cluster.role", "worker"),
                meta={
                    "pid": os.getpid(),
                    "port": cfg.get("webui.port", 8081),
                    "api_url": cfg.get("webui.public_url") or None,
                },
                heartbeat_interval=int(cfg.get("cluster.heartbeat_seconds", 15)),
                ttl_seconds=int(cfg.get("cluster.ttl_seconds", 60)),
            )
            node_registry.register()
            node_registry.start_heartbeat()
            # Expose for other components
            cfg.node_registry = node_registry

            # Cluster files (DB-backed file sync)
            from lib.paths import Paths
            paths = getattr(cfg, "paths", None) or Paths.from_config(
                cfg, root / "config.yml"
            )
            cluster_files = ClusterFiles(
                cfg,
                node_id=node_registry.node_id,
                paths=paths,
                role=node_registry.role,
            )
            cluster_files.initial_sync()
            cluster_files.start_watcher()
            cfg.cluster_files = cluster_files
        except Exception as e:
            logger.warning(f"[cluster] init failed: {e}", command="webui")

    # ─── Election ───
    if cfg.get("cluster.enabled", False) and cfg.get("cluster.election_enabled", False):
        try:
            from lib.cluster.election import Election

            def _on_promote():
                node_registry.role = "primary"
                node_registry.register()
                logger.info("[cluster] promoted to primary", command="webui")

            def _on_demote():
                node_registry.role = "worker"
                node_registry.register()
                logger.info("[cluster] demoted to worker", command="webui")

            election = Election(
                db=node_registry.db,
                node_id=node_registry.node_id,
                lease_seconds=int(cfg.get("cluster.lease_seconds", 30)),
                heartbeat_seconds=int(cfg.get("cluster.heartbeat_seconds", 10)),
                on_promote=_on_promote,
                on_demote=_on_demote,
            )
            election.start()
        except Exception as e:
            logger.warning(f"[cluster] election failed: {e}", command="webui")

    # ─── Cluster WS client (workers connect to primary) ───
    if (cfg.get("cluster.enabled", False)
            and node_registry is not None
            and node_registry.role != "primary"
            and cfg.get("cluster.primary_ws_url")):
        try:
            import asyncio
            from lib.cluster.ws_client import ClusterClient

            client = ClusterClient(
                url=cfg.get("cluster.primary_ws_url"),
                cluster_files=cluster_files,
                token=cfg.get("cluster.ws_token"),
            )

            def run_client():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(client.run())
                finally:
                    loop.close()

            t = threading.Thread(
                target=run_client, daemon=True, name="homer-cluster-ws",
            )
            t.start()
            cluster_client = t
            logger.info(
                f"[cluster] WS client started -> "
                f"{cfg.get('cluster.primary_ws_url')}",
                command="webui",
            )
        except Exception as e:
            logger.warning(f"[cluster] ws client failed: {e}", command="webui")

    # ─── Metrics collectors ───
    from lib.metrics.collectors import ClusterCollector, I18nCollector

    i18n_collector = I18nCollector(interval=15)
    i18n_collector.start()

    cluster_collector = None
    try:
        from lib.cluster.ws_server import get_hub
        cluster_collector = ClusterCollector(
            cfg,
            node_registry=node_registry,
            ws_hub=get_hub(),
            cluster_files=cluster_files,
            interval=15.0,
        )
        cluster_collector.start()
    except Exception as e:
        logger.warning(f"[metrics] cluster collector failed: {e}",
                       command="webui")

    # ─── SSL / ports ───
    ssl_cfg = cfg.get('webui.ssl', {}) or {}
    ssl_enabled = bool(ssl_cfg.get('enabled', False))
    cert = ssl_cfg.get('cert')
    key = ssl_cfg.get('key')

    http_port = int(args.get('port') or cfg.get('webui.port', 80))
    https_port = int(args.get('ssl_port') or ssl_cfg.get('port', 443))
    redirect_http = bool(ssl_cfg.get('redirect_http', True))

    host = args.get('host') or cfg.get('webui.host', '0.0.0.0')

    app = create_app(cfg, root_dir=root, logger=logger)

    # ─── Signals ───
    servers = []

    def _stop(*_):
        for s in servers:
            try:
                s.should_exit = True
            except Exception:
                pass

    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, 'SIGHUP'):
        def _on_hup(*_):
            logger.info("[webui] SIGHUP — reloading config", command="webui")
            try:
                cfg.reload()
                from lib.i18n import get_i18n
                get_i18n().reload()
            except Exception as e:
                logger.error(f"[webui] reload failed: {e}",
                             command="webui", exc_info=True)
        signal.signal(signal.SIGHUP, _on_hup)

    # ─── HTTP→HTTPS redirect ───
    if ssl_enabled and redirect_http and http_port and http_port != https_port:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import RedirectResponse

        async def _redirect(request):
            host_only = request.url.hostname
            new = f"https://{host_only}"
            if https_port != 443:
                new += f":{https_port}"
            new += str(request.url.path)
            if request.url.query:
                new += '?' + request.url.query
            return RedirectResponse(new, status_code=301)

        redirect_app = Starlette(routes=[Route('/{path:path}', _redirect)])
        http_server = uvicorn.Server(uvicorn.Config(
            redirect_app, host=host, port=http_port,
            log_level='warning', access_log=False, log_config=None,
        ))
        http_server.install_signal_handlers = lambda: None
        servers.append(http_server)
        logger.info(f"[webui] HTTP→HTTPS redirect :{http_port} → :{https_port}",
                    command="webui")

    # ─── Main server ───
    if ssl_enabled:
        if not cert or not key:
            logger.error("[webui] ssl.cert/ssl.key not set", command="webui")
            return 1
        ssl_kwargs = {
            'ssl_certfile': cert,
            'ssl_keyfile': key,
        }
        if ssl_cfg.get('ca'):
            ssl_kwargs['ssl_ca_certs'] = ssl_cfg['ca']
        if ssl_cfg.get('require_client_cert'):
            ssl_kwargs['ssl_cert_reqs'] = 2
        main_port = https_port
        scheme = 'https'
    else:
        ssl_kwargs = {}
        main_port = http_port
        scheme = 'http'

    main_server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=main_port,
        log_level=cfg.get('webui.log_level', 'info'),
        access_log=False, log_config=None,
        **ssl_kwargs,
    ))
    main_server.install_signal_handlers = lambda: None
    servers.append(main_server)
    logger.info(f"[webui] {scheme}://{host}:{main_port}/ (pid {os.getpid()})",
                command="webui")

    if len(servers) > 1:
        redirect_thread = threading.Thread(
            target=servers[0].run, daemon=True,
        )
        redirect_thread.start()

    # ─── Run ───
    try:
        main_server.run()
    finally:
        _stop()
        try:
            if cluster_collector:
                cluster_collector.stop()
            i18n_collector.stop()
        except Exception:
            pass
        try:
            if election:
                election.stop()
            if cluster_files:
                cluster_files.stop_watcher()
            if node_registry:
                node_registry.stop_heartbeat()
                node_registry.unregister()
        except Exception:
            pass
        logger.info("[webui] stopped", command="webui")
    return 0


# ─────────── Утилиты ───────────

def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m:02d}m"


def _print_access_hint(context):
    cfg = context['config']
    host = cfg.get('webui.host', '127.0.0.1')
    port = cfg.get('webui.port', 8080)
    console.key_value('URL', f"http://{host}:{port}/")
    console.comment("Остановить: homer webui:stop")
    console.comment("Перезапустить: homer webui:restart")
    console.comment("Перечитать конфиг: homer webui:reload")
