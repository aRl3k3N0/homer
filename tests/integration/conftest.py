"""
Integration fixtures: spawn a real Web UI process on a random port,
talk to it over HTTP/WebSocket.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, Optional

import pytest

from tests._helpers.cli_runner import make_cli_runner, REPO_ROOT


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.status in (200, 401, 403)
        except urllib.error.HTTPError as e:
            if e.code in (200, 401, 403, 307):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


class HomerProcess:
    """
    Homer Web UI running as a subprocess.

    Provides helpers for HTTP and WS access.
    """

    def __init__(self, process: subprocess.Popen, port: int, project_dir: Path):
        self.process = process
        self.port = port
        self.project_dir = Path(project_dir)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_base(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def stop(self, timeout: float = 5.0):
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=timeout)


@pytest.fixture
def homer_process_factory(tmp_path) -> Iterator:
    """
    Factory that spawns a Homer process in an isolated project.
    Yields a callable: make(name='node-a', extra_yaml='...') -> HomerProcess.
    """
    processes: list[HomerProcess] = []

    def _make(name: str = "node", *, extra_yaml: str = "",
              cluster_role: str = "worker",
              join_url: Optional[str] = None,
              join_token: Optional[str] = None) -> HomerProcess:
        project_dir = tmp_path / name
        project_dir.mkdir(parents=True, exist_ok=True)

        runner = make_cli_runner(project_dir, extra_yaml=f"""
        cluster:
          enabled: true
          role: {cluster_role}
          ttl_seconds: 60
          heartbeat_seconds: 5
          election_enabled: false
        {extra_yaml}
        """)

        port = _free_port()

        env = os.environ.copy()
        env["HOMER_CONFIG"] = str(project_dir / "config.yml")
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd = [
            sys.executable,
            str(REPO_ROOT / "homer"),
            "_webui_run",
            f"--host=127.0.0.1",
            f"--port={port}",
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )

        hp = HomerProcess(proc, port, project_dir)
        processes.append(hp)

        # Wait for HTTP
        ok = _wait_http(f"{hp.base_url}/healthz", timeout=20)
        if not ok:
            hp.stop()
            try:
                log = proc.stdout.read() if proc.stdout else ""
            except Exception:
                log = ""
            raise RuntimeError(
                f"Homer did not start on {hp.base_url}. Output:\n{log}"
            )

        return hp

    yield _make

    for hp in processes:
        try:
            hp.stop()
        except Exception:
            pass
