"""
Внутренние и публичные команды управления Web UI.

Публичные:
    webui:start    — запустить в фоне (PID в var/webui.pid)
    webui:stop     — остановить
    webui:restart  — перезапустить
    webui:reload   — SIGHUP: перечитать конфиг
    webui:status   — статус

Внутренняя:
    _webui_run     — сам процесс сервера (не вызывайте вручную)
"""
import os
import sys
from pathlib import Path

from lib.console import console, Color
from lib.daemon import ServiceManager, ServiceStatus


DESCRIPTIONS = {
    'start':   "Запустить Web UI в фоне (как pg_ctl)",
    'stop':    "Остановить Web UI",
    'restart': "Перезапустить Web UI",
    'reload':  "Перечитать конфиг Web UI (SIGHUP)",
    'status':  "Статус Web UI",
    'logs':    "Показать хвост лога Web UI",
}


# ─────────── Helpers ───────────

def _manager(context) -> ServiceManager:
    return ServiceManager(Path(context['root_dir']), 'webui')


def _homer_argv(context) -> list[str]:
    """Полная команда запуска внутреннего процесса."""
    root = Path(context['root_dir'])
    homer = root / 'homer'
    argv = [sys.executable, str(homer), '_webui_run']

    # Пробрасываем интересные аргументы
    args = context['args']
    if args.get('host'):
        argv.append(f"--host={args['host']}")
    if args.get('port'):
        argv.append(f"--port={args['port']}")
    if args.get('workers'):
        argv.append(f"--workers={args['workers']}")
    return argv


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
    return 0 if st.status == ServiceStatus.RUNNING else 0


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


# ─────────── Внутренняя команда: сам процесс ───────────

def _run(context):
    import signal
    import uvicorn
    from lib.webui import create_app
    from lib.logger import Logger
    from lib.metrics.collectors import I18nCollector

    collector = I18nCollector(interval=15)
    collector.start()

    cfg = context['config']
    root = Path(context['root_dir'])
    args = context['args']
    logger = Logger(cfg, root)

    ssl_cfg = cfg.get('webui.ssl', {}) or {}
    ssl_enabled = bool(ssl_cfg.get('enabled', False))
    cert = ssl_cfg.get('cert')
    key = ssl_cfg.get('key')

    # Порты
    http_port = int(args.get('port') or cfg.get('webui.port', 80))
    https_port = int(args.get('ssl_port') or ssl_cfg.get('port', 443))
    redirect_http = bool(ssl_cfg.get('redirect_http', True))

    host = args.get('host') or cfg.get('webui.host', '0.0.0.0')

    auth = None   # больше не нужен — используем AuthManager
    app = create_app(cfg, root_dir=root, logger=logger)

    # ── Сигналы ──
    servers = []

    def _stop(*_):
        for s in servers:
            try: s.should_exit = True
            except Exception: pass

    signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, lambda *_: cfg.load())

    # ── HTTP-редирект на HTTPS (если ssl enabled) ──
    if ssl_enabled and redirect_http and http_port and http_port != https_port:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import RedirectResponse

        async def _redirect(request):
            url = request.url.replace(
                scheme='https',
                port=https_port,
            )
            # netloc с портом
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
        logger.info(f"[webui] HTTP→HTTPS редирект на :{http_port} → :{https_port}")

    # ── Основной сервер ──
    if ssl_enabled:
        if not cert or not key:
            logger.error("[webui] ssl.cert/ssl.key не заданы")
            return 1
        ssl_kwargs = {
            'ssl_certfile': cert,
            'ssl_keyfile': key,
        }
        if ssl_cfg.get('ca'):
            ssl_kwargs['ssl_ca_certs'] = ssl_cfg['ca']
        if ssl_cfg.get('require_client_cert'):
            ssl_kwargs['ssl_cert_reqs'] = 2   # CERT_REQUIRED
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
    logger.info(f"[webui] {scheme}://{host}:{main_port}/ (pid {os.getpid()})")

    if len(servers) > 1:
        import threading
        redirect_thread = threading.Thread(
            target=servers[0].run, daemon=True,
        )
        redirect_thread.start()

    try:
        main_server.run()
    finally:
        _stop()
        logger.info("[webui] Остановлен")
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
    console.comment(f"Остановить: homer webui:stop")
    console.comment(f"Перезапустить: homer webui:restart")
    console.comment(f"Перечитать конфиг: homer webui:reload")

def tail(context):
    """Постоянный follow лога. Ctrl+C для выхода."""
    import time
    from pathlib import Path
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
            f.seek(0, 2)   # конец файла
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
    from pathlib import Path
    from lib.queue import QueueStorage
    from lib.daemon import ServiceManager, ServiceStatus

    cfg = context['config']
    root = Path(context['root_dir'])
    mgr = ServiceManager(root, 'scheduler', config=cfg)
    st = mgr.status()

    console.banner("Scheduler workers",
                   f"{st.status} pid={st.pid or '—'}")

    storage = QueueStorage(cfg)
    try:
        stats = storage.stats()
        rows = [
            ['running', stats.get('running', 0)],
            ['pending', stats.get('pending', 0)],
            ['done',    stats.get('done', 0)],
            ['failed',  stats.get('failed', 0)],
        ]
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
