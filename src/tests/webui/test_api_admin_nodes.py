"""
Tests for /api/admin/nodes/*.
"""
import json
from datetime import datetime


def test_admin_nodes_page_renders(client, auth_headers):
    r = client.get("/admin/nodes", headers=auth_headers)
    assert r.status_code == 200
    assert "Nodes" in r.text or "nodes" in r.text


def test_list_nodes(client, auth_headers):
    r = client.get("/api/admin/nodes", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_node_diagnostics_404_for_unknown(client, auth_headers):
    r = client.get("/api/admin/nodes/unknown-id/diagnostics",
                   headers=auth_headers)
    assert r.status_code == 404


def test_restart_rejects_invalid_mode(client, auth_headers):
    r = client.post(
        "/api/admin/nodes/some-id/restart",
        json={"mode": "bogus"},
        headers=auth_headers,
    )
    # 400 for bad mode (checked before node lookup) or 404 for unknown node
    assert r.status_code in (400, 404)


def test_diagnostics_endpoint_responds(client):
    """
    /api/diagnostics is public (used by peer nodes).
    """
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    data = r.json()
    assert "hostname" in data
    assert "pid" in data
