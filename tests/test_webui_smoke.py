# tests/test_webui_smoke.py
def test_create_app_returns_app(tmp_config, tmp_path):
    from lib.webui import create_app
    app = create_app(tmp_config, root_dir=tmp_path)
    assert app is not None, "create_app() вернул None!"
    assert hasattr(app, 'routes'), "create_app() вернул не FastAPI"
    assert len(app.routes) > 0
