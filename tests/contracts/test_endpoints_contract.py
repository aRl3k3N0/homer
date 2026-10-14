"""
Contract checks: every JSON endpoint returns a JSON-serializable body
with expected content-type when called with valid auth.
"""
import json
import pytest


JSON_ENDPOINTS_GET = [
    "/api/stats",
    "/api/jobs",
    "/api/editor/config/tree",
    "/api/editor/config/section?path=app",
    "/api/editor/config/export",
    "/api/editor/tree/commands",
    "/api/editor/lock",
    "/api/editor/history",
    "/api/editor/langs",
    "/api/admin/nodes",
]


@pytest.mark.parametrize("path", JSON_ENDPOINTS_GET)
def test_get_endpoints_return_json(client, auth_headers, path):
    r = client.get(path, headers=auth_headers)
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
    ct = r.headers.get("content-type", "")
    assert "application/json" in ct, f"{path}: content-type={ct}"
    # Must be parseable
    body = r.json()
    assert body is not None


def test_healthz_no_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_diagnostics_no_auth(client):
    r = client.get("/api/diagnostics")
    assert r.status_code == 200


def test_protected_endpoints_require_auth(client):
    protected = [
        "/api/stats",
        "/api/jobs",
        "/api/editor/config/tree",
        "/api/admin/nodes",
    ]
    for path in protected:
        r = client.get(path)
        # 401, 403 or 307 redirect to /login
        assert r.status_code in (401, 403, 307), \
            f"{path}: expected auth error, got {r.status_code}"


def test_error_shape(client, auth_headers):
    """Missing keys should return {'detail': '...'}."""
    r = client.get("/api/editor/config/nope.nope", headers=auth_headers)
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body


def test_invalid_category_returns_404(client, auth_headers):
    r = client.get("/api/editor/tree/not-a-category", headers=auth_headers)
    assert r.status_code == 404


def test_bad_query_params(client, auth_headers):
    # limit must be >= 1
    r = client.get("/api/jobs?limit=0", headers=auth_headers)
    assert r.status_code == 422


def test_websocket_endpoint_registered(routes_index):
    ws_paths = [path for (m, path) in routes_index if m == "WS"]
    assert any("/ws" == p for p in ws_paths)
    assert any("/ws/cluster" in p for p in ws_paths)
