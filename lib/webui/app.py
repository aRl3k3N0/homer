"""
FastAPI-приложение для Web UI Homer.

Единый источник эндпоинтов:
    HTML:      /, /jobs/{id}, /history, /history/{id}, /logs, /console
    API:       /api/stats, /api/jobs, /api/jobs/{id}, /api/history*, /api/logs*
    Действия:  POST /jobs/{id}/cancel, /jobs/{id}/retry, /jobs/purge
    WS:        /ws, /ws/logs, /ws/console
    Служебные: /healthz, /metrics, /docs, /redoc, /openapi.json
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime
from lib.i18n import get_i18n
from jinja2 import select_autoescape, Environment
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    Depends,
    Query,
    Path as FPath,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.openapi.utils import get_openapi
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    FileResponse,
    StreamingResponse,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lib.queue import QueueStorage
from lib.queue.models import JobStatus
from lib.webui.console_session import ConsoleSession
from lib.webui.history import HistoryStorage
from lib.webui.logs_reader import LogsReader
from lib.webui.schemas import (
    JobSchema,
    StatsSchema,
    HealthSchema,
    PurgeResponse,
    ErrorResponse,
)
from lib.webui.ws import get_hub


TEMPLATES_DIR = Path(__file__).parent / 'templates'
STATIC_DIR = Path(__file__).parent / 'static'


TAGS_METADATA = [
    {
        'name': 'jobs',
        'description': 'Операции с задачами очереди: список, детали, отмена, retry.',
    },
    {
        'name': 'stats',
        'description': 'Статистика очереди: счётчики по статусам.',
    },
    {
        'name': 'actions',
        'description': 'Действия над задачами: cancel, retry, purge.',
    },
    {
        'name': 'system',
        'description': 'Служебные эндпоинты: healthcheck, metrics.',
    },
]

def create_app(
    config,
    root_dir=None,
    auth: Optional[tuple[str, str]] = None,
    enable_docs: bool = True,
    logger=None,
):
    """
    Создаёт FastAPI-приложение.

    config       — объект Config
    root_dir     — Path к корню проекта (для commands/, logs/)
    auth         — (user, password) для Basic Auth или None
    enable_docs  — включить /docs, /redoc, /openapi.json
    logger       — экземпляр lib.logger.Logger (для интерактивных команд)
    """
    if not config.get('webui.enabled', True):
        # Отдаём минимальную заглушку, чтобы uvicorn.run() не упал на None
        stub = FastAPI()

        @stub.get('/')
        def _disabled():
            return {'ok': False, 'error': 'Web UI отключён в config.yml (webui.enabled=false)'}

        return stub

    root_dir = Path(root_dir) if root_dir else Path('.')

    app = FastAPI(
        title='Homer Queue API',
        description=(
            'REST API для мониторинга и управления очередью Homer.\n\n'
            'Все эндпоинты, кроме `/healthz` и `/metrics`, требуют Basic Auth, '
            'если настроен `webui.auth` в конфиге.\n\n'
            '**Основные возможности:**\n'
            '- Просмотр задач с фильтрами по статусу и поиском.\n'
            '- Детали задачи: аргументы, ошибки, вывод, дети.\n'
            '- Отмена (с каскадом по потомкам) и повтор.\n'
            '- Очистка старых завершённых задач.\n'
            '- Статистика по статусам.\n'
            '- Логи (просмотр, скачивание, live-tail).\n'
            '- История запусков команд из Web UI Console.\n'
            '- WebSocket-обновления в реальном времени.\n'
        ),
        version=config.get('app.version', '1.0.0'),
        contact={'name': 'Homer', 'url': config.get('webui.contact_url', '') or ''},
        license_info={
            'name': 'MIT',
            'url': 'https://opensource.org/licenses/MIT',
        },
        openapi_tags=TAGS_METADATA,
        docs_url='/docs' if enable_docs else None,
        redoc_url='/redoc' if enable_docs else None,
        openapi_url='/openapi.json' if enable_docs else None,
    )

    if STATIC_DIR.exists():
        app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

    #templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    from lib.plugins import get_manager
    plugin_mgr = get_manager()

    # Jinja: основной каталог + каталоги плагинов
    from jinja2 import ChoiceLoader, FileSystemLoader
    from fastapi.templating import Jinja2Templates

    search_dirs = [TEMPLATES_DIR]
    for p in plugin_mgr.list():
        if p.templates_dir:
            search_dirs.append(p.templates_dir)

    templates_env = Environment(
        loader=ChoiceLoader([FileSystemLoader(str(d)) for d in search_dirs]),
        autoescape=select_autoescape(['html', 'xml']),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    i18n = get_i18n()

    # Jinja global: {{ _('webui.jobs.title') }}
    templates_env.globals['_'] = i18n.jinja_global()
    templates_env.globals['locale'] = i18n.locale
    templates = Jinja2Templates(env=templates_env)

    # Статика: /static/plugins/<plugin>/...
    for p in plugin_mgr.list():
        if p.static_dir:
            app.mount(
                f'/static/plugins/{p.name}',
                StaticFiles(directory=str(p.static_dir)),
                name=f'plugin-static-{p.name}',
            )

    # ─────────── Внешние сервисы ───────────

    security = HTTPBasic(auto_error=False)
    hub = get_hub()

    # Логи — из <root>/logs
    logs_reader = LogsReader(root_dir / 'var/log')

    # История — ленивая
    _history_storage: Optional[HistoryStorage] = None

    def get_history() -> HistoryStorage:
        nonlocal _history_storage
        if _history_storage is None:
            _history_storage = HistoryStorage(config)
        return _history_storage

    def get_storage() -> QueueStorage:
        return QueueStorage(config)

    # ─────────── AUTH ───────────

    def check_auth(creds: Optional[HTTPBasicCredentials] = Depends(security)):
        if auth is None:
            return True
        if creds is None or (creds.username, creds.password) != auth:
            raise HTTPException(
                status_code=401,
                detail='Unauthorized',
                headers={'WWW-Authenticate': 'Basic realm="Homer Queue"'},
            )
        return True

    def current_user(request_or_ws) -> str:
        if auth is None:
            return 'anonymous'
        # WebSocket — query
        if isinstance(request_or_ws, WebSocket):
            q = request_or_ws.query_params
            return q.get('user', 'anonymous')
        # HTTP — Basic Auth
        h = request_or_ws.headers.get('authorization', '')
        if h.lower().startswith('basic '):
            import base64
            try:
                raw = base64.b64decode(h.split(' ', 1)[1]).decode('utf-8')
                return raw.split(':', 1)[0] or 'anonymous'
            except Exception:
                pass
        return 'anonymous'

    # ─────────── Фильтры Jinja ───────────

    def status_color(status: str) -> str:
        return {
            'pending': 'warning',
            'running': 'info',
            'done': 'success',
            'failed': 'danger',
            'canceled': 'secondary',
            'timeout': 'dark',
        }.get(status, 'light')

    templates.env.filters['status_color'] = status_color

    # ─────────── Хелперы ───────────

    def job_to_dict(job) -> dict:
        return {
            'id': job.id,
            'command': job.command,
            'args': job.args,
            'priority': job.priority,
            'status': job.status,
            'attempts': job.attempts,
            'max_attempts': job.max_attempts,
            'retry_delay': job.retry_delay,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
            'run_at': job.run_at.isoformat() if job.run_at else None,
            'exit_code': job.exit_code,
            'error': job.error,
            'result': (job.result or '')[:2000],
            'triggered_by': job.triggered_by,
            'parent_job_id': job.parent_job_id,
        }

    # ═══════════════════════════════════════════════════════════════
    #  HTML-СТРАНИЦЫ
    # ═══════════════════════════════════════════════════════════════

    @app.get('/', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def index(request: Request, status: Optional[str] = None,
              q: Optional[str] = None):
        storage = get_storage()
        try:
            jobs = storage.list(status=status or None, limit=200)
            stats = storage.stats()
            jobs_dict = [job_to_dict(j) for j in jobs]
            if q:
                jobs_dict = [
                    j for j in jobs_dict
                    if q.lower() in j['command'].lower()
                    or q.lower() in str(j['args']).lower()
                ]
        finally:
            storage.close()

        return templates.TemplateResponse('index.html', {
            'request': request,
            'jobs': jobs_dict,
            'stats': stats,
            'filter_status': status,
            'query': q or '',
            'statuses': [
                'pending', 'running', 'done', 'failed', 'canceled', 'timeout',
            ],
        })

    @app.get('/jobs/{job_id}', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def job_detail(request: Request, job_id: int):
        storage = get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail='Job not found')
            children = [j for j in storage.list(limit=500)
                        if j.parent_job_id == job_id]
            children_dict = [job_to_dict(j) for j in children]
        finally:
            storage.close()

        return templates.TemplateResponse('job.html', {
            'request': request,
            'job': job_to_dict(job),
            'children': children_dict,
        })

    @app.get('/history', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def history_page(request: Request, command: Optional[str] = None,
                     limit: int = 100):
        storage = get_history()
        user = current_user(request)
        entries = storage.list(user=user, command=command, limit=limit)
        commands = storage.distinct_commands(user=user)
        return templates.TemplateResponse('history.html', {
            'request': request,
            'entries': entries,
            'commands': commands,
            'selected_command': command or '',
            'user': user,
        })

    @app.get('/history/{entry_id}', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def history_detail(request: Request, entry_id: str):
        storage = get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(status_code=404)
        if entry.user != current_user(request):
            raise HTTPException(status_code=403)
        return templates.TemplateResponse('history_detail.html', {
            'request': request,
            'entry': entry,
        })

    @app.get('/logs', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def logs_index(request: Request,
                   command: Optional[str] = None,
                   date_: Optional[str] = None,
                   level: Optional[str] = None,
                   grep: Optional[str] = None,
                   limit: int = 500):
        files = logs_reader.list_files()
        commands = logs_reader.list_commands()
        entries = []

        target_command = command
        target_date = date_

        if not target_command and files:
            target_command = files[0].command
            target_date = target_date or files[0].date.isoformat()

        if target_command and target_date:
            try:
                entries = logs_reader.read(
                    target_command, target_date,
                    level=level, grep=grep, limit=limit,
                )
            except Exception:
                entries = []

        return templates.TemplateResponse('logs.html', {
            'request': request,
            'files': files,
            'commands': commands,
            'entries': entries,
            'selected_command': target_command,
            'selected_date': target_date,
            'selected_level': level or '',
            'grep': grep or '',
            'limit': limit,
        })

    @app.get('/console', response_class=HTMLResponse,
             dependencies=[Depends(check_auth)])
    def console_page(request: Request):
        from lib.command_loader import CommandLoader
        loader = CommandLoader(root_dir / 'commands')
        commands = list(loader.load_commands().keys())
        try:
            from lib.commands import BUILTIN_COMMANDS
            commands += list(BUILTIN_COMMANDS.keys())
        except Exception:
            pass
        return templates.TemplateResponse('console.html', {
            'request': request,
            'commands': sorted(set(commands)),
        })

    # ═══════════════════════════════════════════════════════════════
    #  API: ЗАДАЧИ
    # ═══════════════════════════════════════════════════════════════

    @app.get('/api/stats', response_model=StatsSchema, tags=['stats'],
             summary='Статистика очереди',
             dependencies=[Depends(check_auth)])
    def api_stats():
        storage = get_storage()
        try:
            return storage.stats()
        finally:
            storage.close()

    @app.get('/api/jobs', response_model=list[JobSchema], tags=['jobs'],
             summary='Список задач',
             dependencies=[Depends(check_auth)])
    def api_jobs(
        status: Optional[str] = Query(
            None,
            description='Фильтр по статусу',
            pattern='^(pending|running|done|failed|canceled|timeout)$',
        ),
        limit: int = Query(100, ge=1, le=1000, description='Лимит записей'),
    ):
        storage = get_storage()
        try:
            jobs = storage.list(status=status, limit=limit)
            return [job_to_dict(j) for j in jobs]
        finally:
            storage.close()

    @app.get('/api/jobs/{job_id}', response_model=JobSchema, tags=['jobs'],
             summary='Детали задачи',
             responses={404: {'model': ErrorResponse,
                              'description': 'Задача не найдена'}},
             dependencies=[Depends(check_auth)])
    def api_job(job_id: int = FPath(..., ge=1)):
        storage = get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail='Job not found')
            return job_to_dict(job)
        finally:
            storage.close()

    # ═══════════════════════════════════════════════════════════════
    #  API: ДЕЙСТВИЯ
    # ═══════════════════════════════════════════════════════════════

    @app.post('/api/jobs/{job_id}/cancel', response_model=JobSchema,
              tags=['actions'], summary='Отменить задачу',
              dependencies=[Depends(check_auth)])
    def api_cancel(
        job_id: int = FPath(..., ge=1),
        cascade: bool = Query(True, description='Отменять ли дочерние задачи'),
    ):
        storage = get_storage()
        try:
            n = storage.cancel(job_id, cascade=cascade)
            if n == 0:
                raise HTTPException(
                    status_code=400,
                    detail='Не удалось отменить (задача уже выполнена?)',
                )
            return job_to_dict(storage.get(job_id))
        finally:
            storage.close()

    @app.post('/api/jobs/{job_id}/retry', response_model=JobSchema,
              tags=['actions'], summary='Перепоставить задачу',
              dependencies=[Depends(check_auth)])
    def api_retry(job_id: int = FPath(..., ge=1)):
        storage = get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail='Job not found')
            if job.status not in (JobStatus.FAILED, JobStatus.TIMEOUT,
                                  JobStatus.CANCELED):
                raise HTTPException(
                    status_code=400,
                    detail=f'Job в статусе {job.status} — retry не применим',
                )
            storage.retry(job_id)
            return job_to_dict(storage.get(job_id))
        finally:
            storage.close()

    @app.post('/api/jobs/purge', response_model=PurgeResponse,
              tags=['actions'], summary='Удалить завершённые',
              dependencies=[Depends(check_auth)])
    def api_purge(older: int = Query(86400, ge=0,
                                     description='Возраст в секундах')):
        storage = get_storage()
        try:
            return {'purged': storage.purge(older_than_seconds=older)}
        finally:
            storage.close()

    # ─────────── HTML-формы (redirect версии) ───────────

    @app.post('/jobs/{job_id}/cancel', dependencies=[Depends(check_auth)])
    def form_cancel(job_id: int, cascade: bool = True):
        storage = get_storage()
        try:
            n = storage.cancel(job_id, cascade=cascade)
            if n == 0:
                raise HTTPException(status_code=400,
                                    detail='Не удалось отменить')
            return RedirectResponse(f'/jobs/{job_id}', status_code=303)
        finally:
            storage.close()

    @app.post('/jobs/{job_id}/retry', dependencies=[Depends(check_auth)])
    def form_retry(job_id: int):
        storage = get_storage()
        try:
            job = storage.get(job_id)
            if not job:
                raise HTTPException(status_code=404)
            if job.status not in (JobStatus.FAILED, JobStatus.TIMEOUT,
                                  JobStatus.CANCELED):
                raise HTTPException(status_code=400,
                                    detail=f'Job в статусе {job.status}')
            storage.retry(job_id)
            return RedirectResponse(f'/jobs/{job_id}', status_code=303)
        finally:
            storage.close()

    @app.post('/jobs/purge', dependencies=[Depends(check_auth)])
    def form_purge(older: int = 86400):
        storage = get_storage()
        try:
            return {'purged': storage.purge(older_than_seconds=older)}
        finally:
            storage.close()

    # ═══════════════════════════════════════════════════════════════
    #  API: ИСТОРИЯ
    # ═══════════════════════════════════════════════════════════════

    @app.get('/api/history', dependencies=[Depends(check_auth)])
    def api_history(request: Request,
                    command: Optional[str] = None,
                    limit: int = 100,
                    offset: int = 0):
        storage = get_history()
        user = current_user(request)
        entries = storage.list(user=user, command=command,
                               limit=limit, offset=offset)
        return [
            {
                'id': e.id,
                'user': e.user,
                'command': e.command,
                'args': e.args,
                'started_at': e.started_at.isoformat() if e.started_at else None,
                'finished_at': e.finished_at.isoformat() if e.finished_at else None,
                'exit_code': e.exit_code,
                'duration_ms': e.duration_ms,
                'client_ip': e.client_ip,
            }
            for e in entries
        ]

    @app.get('/api/history/{entry_id}', dependencies=[Depends(check_auth)])
    def api_history_entry(entry_id: str, request: Request):
        storage = get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail='Not found')
        if entry.user != current_user(request):
            raise HTTPException(status_code=403, detail='Forbidden')
        return {
            'id': entry.id,
            'user': entry.user,
            'command': entry.command,
            'args': entry.args,
            'started_at': entry.started_at.isoformat() if entry.started_at else None,
            'finished_at': entry.finished_at.isoformat() if entry.finished_at else None,
            'exit_code': entry.exit_code,
            'duration_ms': entry.duration_ms,
            'output': entry.output,
            'input_log': entry.input_log,
            'client_ip': entry.client_ip,
            'user_agent': entry.user_agent,
        }

    @app.delete('/api/history/{entry_id}', dependencies=[Depends(check_auth)])
    def api_history_delete(entry_id: str, request: Request):
        storage = get_history()
        entry = storage.get(entry_id)
        if not entry:
            raise HTTPException(status_code=404)
        if entry.user != current_user(request):
            raise HTTPException(status_code=403)
        storage.db.execute(
            f"DELETE FROM homer_console_history WHERE id = {storage._ph(0)}",
            [entry_id],
        )
        storage.db.commit()
        return {'deleted': entry_id}

    @app.post('/api/history/purge', dependencies=[Depends(check_auth)])
    def api_history_purge(older: int = 86400 * 30):
        storage = get_history()
        return {'purged': storage.purge_older_than(older)}

    # ═══════════════════════════════════════════════════════════════
    #  API: ЛОГИ
    # ═══════════════════════════════════════════════════════════════

    @app.get('/api/logs/files', dependencies=[Depends(check_auth)])
    def api_logs_files():
        return [
            {'command': f.command, 'date': f.date.isoformat(), 'size': f.size}
            for f in logs_reader.list_files()
        ]

    @app.get('/api/logs', dependencies=[Depends(check_auth)])
    def api_logs(command: str, date_: str,
                 level: Optional[str] = None,
                 grep: Optional[str] = None,
                 limit: int = 500):
        entries = logs_reader.read(command, date_, level=level,
                                   grep=grep, limit=limit)
        return [
            {
                'ts': e.ts.isoformat() if e.ts else None,
                'level': e.level,
                'command': e.command,
                'message': e.message,
                'extra': e.extra,
            }
            for e in entries
        ]

    @app.get('/api/logs/download', dependencies=[Depends(check_auth)])
    def download_logs(
        command: str,
        date_: str,
        level: Optional[str] = None,
        grep: Optional[str] = None,
        format: str = 'log',
    ):
        import csv
        import io

        entries = logs_reader.read(command, date_, level=level, grep=grep,
                                   limit=10_000_000, tail=False)

        base_name = f"{command}_{date_}"
        if level:
            base_name += f"_{level}"
        if grep:
            base_name += "_filtered"

        if format == 'log':
            path = logs_reader.logs_dir / f"{command}_{date_}.log"
            if not path.exists():
                raise HTTPException(status_code=404,
                                    detail='Log file not found')
            return FileResponse(
                str(path),
                media_type='text/plain; charset=utf-8',
                filename=f"{base_name}.log",
            )

        if format == 'json':
            body = json.dumps(
                [{
                    'ts': e.ts.isoformat() if e.ts else None,
                    'level': e.level,
                    'command': e.command,
                    'message': e.message,
                    'extra': e.extra,
                } for e in entries],
                ensure_ascii=False, indent=2,
            )
            return Response(
                content=body,
                media_type='application/json; charset=utf-8',
                headers={
                    'Content-Disposition':
                        f'attachment; filename="{base_name}.json"',
                },
            )

        if format == 'jsonl':
            buf = io.StringIO()
            for e in entries:
                buf.write(json.dumps({
                    'ts': e.ts.isoformat() if e.ts else None,
                    'level': e.level,
                    'command': e.command,
                    'message': e.message,
                    'extra': e.extra,
                }, ensure_ascii=False) + '\n')
            return Response(
                content=buf.getvalue(),
                media_type='application/x-ndjson; charset=utf-8',
                headers={
                    'Content-Disposition':
                        f'attachment; filename="{base_name}.jsonl"',
                },
            )

        if format == 'csv':
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['ts', 'level', 'command', 'message'])
            for e in entries:
                writer.writerow([
                    e.ts.isoformat() if e.ts else '',
                    e.level,
                    e.command,
                    e.message,
                ])
            return Response(
                content=buf.getvalue(),
                media_type='text/csv; charset=utf-8',
                headers={
                    'Content-Disposition':
                        f'attachment; filename="{base_name}.csv"',
                },
            )

        raise HTTPException(status_code=400,
                            detail='format: log|json|jsonl|csv')

    @app.get('/api/logs/bundle', dependencies=[Depends(check_auth)])
    def download_logs_bundle(
        date_: str,
        command: Optional[str] = None,
        level: Optional[str] = None,
        grep: Optional[str] = None,
        format: str = 'log',
    ):
        import io
        import zipfile

        files = logs_reader.list_files()
        targets = [f for f in files if f.date.isoformat() == date_]
        if command:
            targets = [f for f in targets if f.command == command]

        if not targets:
            raise HTTPException(status_code=404,
                                detail='Нет файлов для экспорта')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in targets:
                if format == 'log':
                    zf.write(f.path, arcname=f.path.name)
                else:
                    entries = logs_reader.read(
                        f.command, f.date, level=level,
                        grep=grep, tail=False,
                    )
                    if format == 'json':
                        data = json.dumps([{
                            'ts': e.ts.isoformat() if e.ts else None,
                            'level': e.level,
                            'message': e.message,
                        } for e in entries],
                            ensure_ascii=False, indent=2)
                        zf.writestr(f"{f.command}_{f.date.isoformat()}.json", data)
                    elif format == 'jsonl':
                        lines = '\n'.join(json.dumps({
                            'ts': e.ts.isoformat() if e.ts else None,
                            'level': e.level,
                            'message': e.message,
                        }, ensure_ascii=False) for e in entries)
                        zf.writestr(f"{f.command}_{f.date.isoformat()}.jsonl", lines)

        buf.seek(0)
        name = f"homer-logs_{date_}"
        if command:
            name += f"_{command}"
        return StreamingResponse(
            buf,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{name}.zip"',
            },
        )

    # ═══════════════════════════════════════════════════════════════
    #  WEB SOCKETS
    # ═══════════════════════════════════════════════════════════════

    @app.websocket('/ws')
    async def ws_endpoint(websocket: WebSocket):
        if auth is not None:
            q = websocket.query_params
            if (q.get('user'), q.get('pass')) != auth:
                await websocket.close(code=4401, reason='Unauthorized')
                return

        await hub.subscribe(websocket)
        try:
            storage = get_storage()
            try:
                stats = storage.stats()
            finally:
                storage.close()
            await websocket.send_json(
                {'type': 'stats.updated', 'stats': stats}
            )
            while True:
                msg = await websocket.receive_text()
                if msg == 'ping':
                    await websocket.send_text('pong')
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unsubscribe(websocket)

    @app.websocket('/ws/logs')
    async def ws_logs(websocket: WebSocket, command: str,
                      date_: Optional[str] = None):
        if auth is not None:
            q = websocket.query_params
            if (q.get('user'), q.get('pass')) != auth:
                await websocket.close(code=4401, reason='Unauthorized')
                return

        await websocket.accept()
        target_date = date_ or date.today().isoformat()

        try:
            initial = logs_reader.read(command, target_date, limit=200)
            for e in initial:
                await websocket.send_json({
                    'ts': e.ts.isoformat() if e.ts else None,
                    'level': e.level,
                    'message': e.message,
                })

            path = logs_reader.logs_dir / f"{command}_{target_date}.log"
            offset = path.stat().st_size if path.exists() else 0

            while True:
                await asyncio.sleep(0.5)
                today = date.today().isoformat()
                if today != target_date:
                    target_date = today
                    offset = 0

                new_offset, lines = logs_reader.tail_lines(
                    command, target_date, offset,
                )
                if new_offset != offset:
                    offset = new_offset
                    for line in lines:
                        entry = logs_reader._parse_line(line, command)
                        if entry:
                            await websocket.send_json({
                                'ts': entry.ts.isoformat() if entry.ts else None,
                                'level': entry.level,
                                'message': entry.message,
                            })
        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({'error': str(e)})
            except Exception:
                pass

    @app.websocket('/ws/console')
    async def ws_console(websocket: WebSocket):
        if auth is not None:
            q = websocket.query_params
            if (q.get('user'), q.get('pass')) != auth:
                await websocket.close(code=4401, reason='Unauthorized')
                return

        await websocket.accept()

        try:
            init = await websocket.receive_json()
        except Exception:
            await websocket.close(code=4400, reason='Ожидалось JSON-сообщение')
            return

        command = init.get('command')
        args = init.get('args') or {}

        if not command:
            await websocket.send_json({'type': 'error',
                                       'message': 'command обязателен'})
            await websocket.close()
            return

        allow = config.get('webui.console.allow_commands') or []
        if allow and command not in allow:
            await websocket.send_json({'type': 'error',
                                       'message': 'Команда запрещена'})
            await websocket.close()
            return

        # Отдельный Logger на команду — если он не передан,
        # создаём свой (не модуль!)
        if logger is not None:
            cmd_logger = logger
        else:
            from lib.logger import Logger
            cmd_logger = Logger(config, root_dir / 'logs')

        session = ConsoleSession(
            context={
                'config': config,
                'logger': cmd_logger,
                'root_dir': root_dir,
            },
            command=command,
            args=args,
            history=get_history(),
            user=current_user(websocket),
            client_ip=websocket.client.host if websocket.client else None,
            user_agent=websocket.headers.get('user-agent'),
            session_id=init.get('history_id') or str(uuid.uuid4()),
        )
        session.start()

        async def pump_output():
            while session.is_alive or not session._messages.empty():
                msg = session.get_message(timeout=0.2)
                if msg is None:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    await websocket.send_json(msg)
                except Exception:
                    return

        pump_task = asyncio.create_task(pump_output())

        try:
            while True:
                try:
                    data = await websocket.receive_json()
                except WebSocketDisconnect:
                    break
                except Exception:
                    continue

                t = data.get('type')
                if t == 'input_response':
                    session.send_input(data.get('id', ''),
                                       data.get('value', ''))
                elif t == 'signal' and data.get('signal') == 'SIGINT':
                    session.stop()
        except WebSocketDisconnect:
            pass
        finally:
            session.stop()
            pump_task.cancel()

    # ═══════════════════════════════════════════════════════════════
    #  СЛУЖЕБНЫЕ
    # ═══════════════════════════════════════════════════════════════

    @app.get('/healthz', response_model=HealthSchema, tags=['system'],
             summary='Проверка работоспособности')
    def healthz():
        try:
            storage = get_storage()
            storage.stats()
            storage.close()
            return {'ok': True}
        except Exception as e:
            return JSONResponse({'ok': False, 'error': str(e)},
                                status_code=503)

    @app.get('/metrics', tags=['system'], summary='Prometheus-метрики',
             response_class=Response,
             responses={200: {'content': {'text/plain': {}}}})
    def metrics():
        try:
            from lib.metrics import metrics_endpoint
        except ImportError:
            return Response(content=b'# metrics module not available\n',
                            media_type='text/plain')
        body, ctype = metrics_endpoint()
        return Response(content=body, media_type=ctype)

    # ═══════════════════════════════════════════════════════════════
    #  STARTUP / SHUTDOWN — фоновый publisher для /ws
    # ═══════════════════════════════════════════════════════════════

    @app.on_event('startup')
    async def _startup_publisher():
        async def publisher():
            last_snapshot: dict[int, str] = {}
            last_stats: dict = {}
            while True:
                try:
                    storage = get_storage()
                    try:
                        jobs = storage.list(limit=500)
                        stats = storage.stats()
                    finally:
                        storage.close()

                    current = {j.id: j.status for j in jobs}

                    for j in jobs:
                        if j.id not in last_snapshot:
                            await hub.broadcast({
                                'type': 'job.created',
                                'job': job_to_dict(j),
                            })
                        elif last_snapshot[j.id] != j.status:
                            await hub.broadcast({
                                'type': 'job.updated',
                                'job': job_to_dict(j),
                            })

                    for jid in set(last_snapshot) - set(current):
                        await hub.broadcast({
                            'type': 'job.removed', 'job_id': jid,
                        })

                    if stats != last_stats:
                        await hub.broadcast({
                            'type': 'stats.updated', 'stats': stats,
                        })
                        last_stats = stats

                    last_snapshot = current
                except Exception as e:
                    if logger is not None:
                        try:
                            logger.warning(f"publisher error: {e}",
                                           command='webui')
                        except Exception:
                            pass

                await asyncio.sleep(2)

        app.state._publisher_task = asyncio.create_task(publisher())

    @app.on_event('shutdown')
    async def _shutdown_publisher():
        t = getattr(app.state, '_publisher_task', None)
        if t:
            t.cancel()
        # Закрываем историю, если создавалась
        if _history_storage is not None:
            try:
                _history_storage.close()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════
    #  Custom OpenAPI
    # ═══════════════════════════════════════════════════════════════

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=TAGS_METADATA,
        )
        schema['servers'] = [
            {'url': config.get('webui.public_url', '/'),
             'description': 'Текущий сервер'},
        ]
        if auth is not None:
            schema.setdefault('components', {}) \
                  .setdefault('securitySchemes', {})['BasicAuth'] = {
                'type': 'http', 'scheme': 'basic',
            }
            schema['security'] = [{'BasicAuth': []}]
        app.openapi_schema = schema
        return schema

    @app.middleware('http')
    async def i18n_middleware(request: Request, call_next):
        # Приоритет: cookie → query → Accept-Language → default
        locale = (
            request.cookies.get('homer_locale')
            or request.query_params.get('lang')
            or _parse_accept_language(request.headers.get('accept-language', ''))
            or i18n.default_locale
        )
        if locale not in i18n.available_locales():
            locale = i18n.fallback_locale

        i18n.set_locale(locale)
        response = await call_next(request)
        response.set_cookie('homer_locale', locale, max_age=365 * 86400,
                            httponly=False, samesite='lax')
        return response

    def _parse_accept_language(header: str) -> Optional[str]:
        """
        'ru-RU,ru;q=0.9,en;q=0.8' → 'ru'
        """
        if not header:
            return None
        for part in header.split(','):
            code = part.split(';')[0].strip()
            if not code:
                continue
            lang = code.split('-')[0].lower()
            if lang:
                return lang
        return None

    app.openapi = custom_openapi

    # ⚠️ ОБЯЗАТЕЛЬНО — единственная точка возврата приложения
    return app
