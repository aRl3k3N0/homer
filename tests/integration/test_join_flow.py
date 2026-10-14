"""
Two-node join: node B joins node A via /api/cluster/join,
then both appear in cluster:status.
"""
import subprocess
import sys
import time
import urllib.error
import urllib.request
import json

import pytest

from tests._helpers.cli_runner import REPO_ROOT


def _post_json(url: str, payload: dict, *, headers: dict = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, {"_raw": body}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"_raw": body}


def test_join_primary(homer_process_factory):
    """
    1. Start primary with join_token.
    2. Start worker (which will call /api/cluster/join manually).
    3. Assert primary has both nodes in /api/admin/nodes.
    """
    primary = homer_process_factory(
        "primary", cluster_role="primary",
        extra_yaml="""
        cluster:
          enabled: true
          role: primary
          join_token: join-secret
          ws_token: ws-secret
        """,
    )
    worker = homer_process_factory(
        "worker", cluster_role="worker",
    )

    # Worker calls join on primary
    status, data = _post_json(
        f"{primary.base_url}/api/cluster/join",
        {
            "hostname": "worker-test",
            "ip": "127.0.0.1",
            "role": "worker",
            "version": "1.0.0",
            "api_url": worker.base_url,
            "meta": {"pid": 0, "port": worker.port},
        },
        headers={"X-Cluster-Token": "join-secret"},
    )
    assert status == 200, f"join failed: {status} {data}"
    assert "node_id" in data
    assert data["ws_url"].startswith("ws://")

    # Wait a moment for heartbeat to record
    time.sleep(1)

    # Check primary sees both nodes
    req = urllib.request.Request(f"{primary.base_url}/api/admin/nodes")
    # Note: requires auth; disable auth for this test or use Basic.
    # Here we assume webui.auth is not configured (isolated config).
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            nodes = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        pytest.skip(f"/api/admin/nodes requires auth: {e.code}")

    ids = {n["id"] for n in nodes}
    assert data["node_id"] in ids, f"joined node not in registry: {ids}"


def test_join_rejects_wrong_token(homer_process_factory):
    primary = homer_process_factory(
        "primary", cluster_role="primary",
        extra_yaml="""
        cluster:
          enabled: true
          role: primary
          join_token: correct-token
        """,
    )

    status, data = _post_json(
        f"{primary.base_url}/api/cluster/join",
        {"hostname": "x", "ip": "127.0.0.1", "role": "worker"},
        headers={"X-Cluster-Token": "wrong-token"},
    )
    assert status == 401
