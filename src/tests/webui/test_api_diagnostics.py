"""
Tests for /api/diagnostics.
"""


def test_diagnostics_shape(client):
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    data = r.json()
    assert "ts" in data
    assert "hostname" in data
    assert "pid" in data
    assert "python_version" in data


def test_diagnostics_includes_i18n(client):
    data = client.get("/api/diagnostics").json()
    assert "i18n" in data
    assert "locales" in data["i18n"]


def test_diagnostics_includes_queue(client):
    data = client.get("/api/diagnostics").json()
    assert "queue" in data
    for key in ("pending", "running", "done", "failed"):
        assert key in data["queue"]
