# tests/test_webui_smoke.py
from base64 import b64encode

from fastapi.testclient import TestClient


def _auth(user="admin", password="admin") -> dict:
    token = b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _bootstrap_admin(tmp_config):
    """Create admin/admin in the isolated auth DB."""
    from homer.auth import AuthStore
    store = AuthStore(tmp_config)
    try:
        user = store.get_user_by_name("admin")
        if user is None:
            uid = store.create_user("admin", password="admin")
            store.assign_role(uid, "admin")
    finally:
        store.close()


def test_create_app_returns_app(tmp_config, tmp_path):
    from homer.webui import create_app
    app = create_app(tmp_config, root_dir=tmp_path)
    assert app is not None
    assert hasattr(app, "routes")
    assert len(app.routes) > 0


def test_webui_homepage_and_static_assets_load(tmp_config, tmp_path):
    from homer.webui import create_app

    _bootstrap_admin(tmp_config)
    app = create_app(tmp_config, root_dir=tmp_path)

    with TestClient(app) as client:
        page = client.get("/", headers=_auth())
        script = client.get("/static/homer-ws.js")

    assert page.status_code == 200, page.text[:300]
    assert script.status_code == 200
    assert "WebSocket" in script.text
