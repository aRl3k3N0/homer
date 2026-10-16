"""
Tests for /api/editor/config/*.
"""
import textwrap


def test_tree_returns_sections(client, auth_headers):
    r = client.get("/api/editor/config/tree", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # The minimal config has at least `app`, `scheduler`, `webui`, `cluster`
    paths = [s["path"] for s in data]
    assert "app" in paths
    assert "scheduler" in paths
    assert "" in paths  # root


def test_tree_requires_auth(client):
    r = client.get("/api/editor/config/tree")
    assert r.status_code in (401, 403, 307)


def test_section_leaves(client, auth_headers):
    r = client.get("/api/editor/config/section?path=app",
                   headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "app"
    names = [e["name"] for e in data["entries"]]
    assert "name" in names
    assert "version" in names


def test_get_value(client, auth_headers):
    r = client.get("/api/editor/config/app.name", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["value"] == "HomerTest"
    assert data["type"] == "string"


def test_get_missing_value(client, auth_headers):
    r = client.get("/api/editor/config/nope.nope", headers=auth_headers)
    assert r.status_code == 404


def test_set_value(client, auth_headers):
    r = client.put(
        "/api/editor/config/app.version",
        json={"value": "9.9.9"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["value"] == "9.9.9"

    # Verify via GET
    r2 = client.get("/api/editor/config/app.version", headers=auth_headers)
    assert r2.json()["value"] == "9.9.9"


def test_set_with_expected_value_conflict(client, auth_headers):
    # Set a known value
    client.put("/api/editor/config/app.version",
               json={"value": "1.0.0"}, headers=auth_headers)

    # Try to update with wrong expected_value
    r = client.put(
        "/api/editor/config/app.version",
        json={"value": "2.0.0", "expected_value": "not-it"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_create_and_delete_value(client, auth_headers):
    r = client.post(
        "/api/editor/config/value",
        json={"path": "app.env", "value": "prod"},
        headers=auth_headers,
    )
    assert r.status_code == 200

    r2 = client.get("/api/editor/config/app.env", headers=auth_headers)
    assert r2.json()["value"] == "prod"

    r3 = client.delete("/api/editor/config/app.env", headers=auth_headers)
    assert r3.status_code == 200

    r4 = client.get("/api/editor/config/app.env", headers=auth_headers)
    assert r4.status_code == 404


def test_create_section(client, auth_headers):
    r = client.post(
        "/api/editor/config/section",
        json={"path": "feature"},
        headers=auth_headers,
    )
    assert r.status_code == 200

    # Now exists in tree
    tree = client.get("/api/editor/config/tree",
                      headers=auth_headers).json()
    assert "feature" in [s["path"] for s in tree]


def test_export_returns_full_config(client, auth_headers):
    r = client.get("/api/editor/config/export", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["app"]["name"] == "HomerTest"


def test_import_applies_updates(client, auth_headers):
    r = client.post(
        "/api/editor/config/import",
        json={"updates": {"app.version": "3.0.0"}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"]["app.version"] == "ok"

    r2 = client.get("/api/editor/config/app.version", headers=auth_headers)
    assert r2.json()["value"] == "3.0.0"
