# tests/test_webui_smoke.py
from fastapi.testclient import TestClient


def test_create_app_returns_app(tmp_config, tmp_path):
    from lib.webui import create_app

    app = create_app(tmp_config, root_dir=tmp_path)
    assert app is not None, "create_app() вернул None!"
    assert hasattr(app, 'routes'), "create_app() вернул не FastAPI"
    assert len(app.routes) > 0


def test_webui_homepage_and_static_assets_load(tmp_config, tmp_path):
    from lib.webui import create_app

    app = create_app(tmp_config, root_dir=tmp_path)

    with TestClient(app) as client:
        page = client.get('/')
        script = client.get('/static/homer-ws.js')

    assert page.status_code == 200
    assert 'Очередь — Homer' in page.text
    assert script.status_code == 200
    assert 'WebSocket' in script.text
