"""
Tests for /api/editor/file/*, /api/editor/tree/*.
"""


def test_tree_commands(client, auth_headers):
    r = client.get("/api/editor/tree/commands", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_write_read_file(client, auth_headers):
    r = client.put(
        "/api/editor/file/commands",
        json={
            "path": "greet.py",
            "content": 'DESCRIPTION = "Greeting"\n',
            "create": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    info = r.json()
    assert info["path"].endswith("greet.py")

    r2 = client.get(
        "/api/editor/file/commands?path=greet.py",
        headers=auth_headers,
    )
    assert r2.status_code == 200
    data = r2.json()
    assert "Greeting" in data["content"]
    assert data["checksum"]


def test_write_with_wrong_checksum_conflicts(client, auth_headers):
    # First write
    client.put(
        "/api/editor/file/commands",
        json={"path": "x.py", "content": "a\n", "create": True},
        headers=auth_headers,
    )
    # Update with wrong expected checksum
    r = client.put(
        "/api/editor/file/commands",
        json={
            "path": "x.py",
            "content": "b\n",
            "expected_checksum": "wrong",
        },
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_delete_file(client, auth_headers):
    client.put(
        "/api/editor/file/commands",
        json={"path": "del.py", "content": "", "create": True},
        headers=auth_headers,
    )
    r = client.request(
        "DELETE",
        "/api/editor/file/commands",
        json={"path": "del.py"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    r2 = client.get(
        "/api/editor/file/commands?path=del.py",
        headers=auth_headers,
    )
    assert r2.status_code == 400


def test_path_traversal_blocked(client, auth_headers):
    r = client.put(
        "/api/editor/file/commands",
        json={
            "path": "../../etc/passwd",
            "content": "x",
            "create": True,
        },
        headers=auth_headers,
    )
    assert r.status_code in (400, 403)


def test_validate_python(client, auth_headers):
    r = client.post(
        "/api/editor/validate",
        json={"category": "commands",
              "path": "x.py",
              "content": "def execute(context): pass"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["errors"] == []


def test_validate_bad_yaml(client, auth_headers):
    r = client.post(
        "/api/editor/validate",
        json={"category": "config",
              "path": "x.yml",
              "content": "a: [unclosed"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert len(r.json()["errors"]) >= 1


def test_category_requires_permission(client, auth_headers):
    r = client.get("/api/editor/tree/static", headers=auth_headers)
    assert r.status_code == 200
