"""
Contract fixtures: build the app once, expose OpenAPI schema.
"""
import pytest

from tests.webui.conftest import (  # noqa: F401
    webui_project, webui_app, client, auth_headers,
)


@pytest.fixture
def openapi_schema(webui_app) -> dict:
    return webui_app.openapi()


@pytest.fixture
def routes_index(webui_app) -> dict:
    """
    Return {(method, path): route} for all routes.
    """
    index = {}
    for route in webui_app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not path:
            continue
        if methods is None:
            # WebSocket routes have no `methods`
            index[("WS", path)] = route
            continue
        for m in methods:
            index[(m, path)] = route
    return index
