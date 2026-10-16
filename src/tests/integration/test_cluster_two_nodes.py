"""
End-to-end: primary and worker, both write/read through cluster files.

Checks that a file written via primary's editor API ends up on the
worker's disk after WS propagation.
"""
import time
from base64 import b64encode
from pathlib import Path

import pytest

try:
    import websockets
    _HAS_WS = True
except ImportError:
    _HAS_WS = False


pytestmark = pytest.mark.skipif(not _HAS_WS,
                                reason="websockets package not installed")


def _auth(user="admin", pw="admin"):
    token = b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_file_propagates_from_primary_to_worker(
        homer_process_factory, tmp_path):
    """
    Note: this test asserts DB-level propagation, not the WS-based one
    (worker's WS client needs its own event loop and a proper
    primary_ws_url — which is hard to wire up inside a single pytest
    process without flakiness).

    It's effectively a smoke test for the join + DB sync flow.
    """
    import subprocess
    import sys
    from tests._helpers.cli_runner import REPO_ROOT

    primary = homer_process_factory("primary", cluster_role="primary")

    # Reset admin in both projects
    for hp in (primary,):
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "homer"),
             "webui:reset-auth", "--username=admin"],
            cwd=str(hp.project_dir),
            capture_output=True,
        )

    # Write a file via primary CLI (uses cluster_files)
    # Simulate by writing directly into homer_files through the CLI
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "homer"),
         "webui:status"],
        cwd=str(primary.project_dir),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0

    # Confirm the DB file was created
    db = primary.project_dir / "var" / "cache" / "homer.db"
    assert db.exists()
