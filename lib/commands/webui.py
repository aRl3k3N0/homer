"""
Web UI для просмотра очереди.
"""
DESCRIPTION = "Запустить веб-интерфейс очереди (FastAPI)"


def execute(context):
    args = context['args']
    config = context['config']

    try:
        import uvicorn
    except ImportError:
        print("Установите зависимости Web UI:")
        print("  pip install 'fastapi>=0.110' 'uvicorn[standard]>=0.29' jinja2")
        return 1

    from lib.webui import create_app

    host = args.get('host') or config.get('webui.host', '127.0.0.1')
    port = int(args.get('port') or config.get('webui.port', 8080))

    auth = None
    if config.get('webui.auth.user'):
        auth = (
            config.get('webui.auth.user'),
            config.get('webui.auth.password', ''),
        )

    app = create_app(config, root_dir=context['root_dir'], auth=auth)

    if app is None:
        print("❌ create_app() вернул None. Проверьте lib/webui/app.py "
              "— в конце функции должен быть `return app`.")
        return 1

    print(f"🌐 Web UI: http://{host}:{port}/")
    if auth:
        print(f"   Basic Auth: {auth[0]}")
    print("   Ctrl+C для остановки")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=config.get('webui.log_level', 'info'),
        access_log=False,
    )
    return 0
