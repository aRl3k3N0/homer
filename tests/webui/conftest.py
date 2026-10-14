"""
WebUI fixtures: isolated project + FastAPI TestClient.
"""
import sys
from pathlib import Path

import pytest

from tests._helpers.cli_runner import make_cli_runner


@pytest.fixture
def webui_project(tmp_path) -> Path:
    runner = make_cli_runner(tmp_path, extra_yaml="""
        webui:
          enabled: true
          auth:
            user: admin
            password: admin
    """)
    return runner.project_dir


@pytest.fixture
def webui_app(webui_project):
    """
    Build the FastAPI app wired to the isolated project.
    """
    from lib.config import Config
    from lib.logger import Logger
    from lib.webui.app import create_app

    cfg_file = webui_project / "config.yml"
    config = Config(cfg_file)

    # Bootstrap admin so Basic Auth works
    from lib.auth import AuthStore
    store = AuthStore(config)
    if not store.get_user_by_name("admin"):
        uid = store.create_user("admin", password="admin")
        store.assign_role(uid, "admin")
    store.close()

    logger = Logger(config, webui_project)
    app = create_app(config, root_dir=webui_project, logger=logger)
    return app


@pytest.fixture
def client(webui_app):
    from fastapi.testclient import TestClient
    with TestClient(webui_app) as c:
        yield c


@pytest.fixture
def auth_headers():
    from base64 import b64encode
    token = b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {token}"}
