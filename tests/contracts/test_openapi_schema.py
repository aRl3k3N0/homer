"""
Validate that the OpenAPI schema is generated and contains the
expected structure and tags.
"""


REQUIRED_TAGS = {"jobs", "stats", "actions", "system"}


def test_openapi_is_generated(openapi_schema):
    assert openapi_schema["openapi"].startswith("3.")
    assert openapi_schema["info"]["title"]


def test_openapi_has_tags(openapi_schema):
    tags = {t["name"] for t in openapi_schema.get("tags", [])}
    assert REQUIRED_TAGS.issubset(tags)


def test_all_paths_have_operations(openapi_schema):
    for path, ops in openapi_schema["paths"].items():
        for method in ops:
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            op = ops[method]
            assert "responses" in op, f"{method.upper()} {path} has no responses"
            assert op["responses"], f"{method.upper()} {path} empty responses"


def test_healthz_is_public(openapi_schema):
    paths = openapi_schema["paths"]
    assert "/healthz" in paths
    assert "get" in paths["/healthz"]


def test_editor_endpoints_present(openapi_schema):
    paths = set(openapi_schema["paths"].keys())
    for p in (
        "/api/editor/config/tree",
        "/api/editor/config/section",
        "/api/editor/config/value",
        "/api/editor/config/rename",
        "/api/editor/config/export",
        "/api/editor/config/import",
        "/api/editor/config/{key_path}",
        "/api/editor/file/{category}",
        "/api/editor/tree/{category}",
        "/api/editor/validate",
        "/api/editor/lock",
        "/api/editor/history",
    ):
        assert p in paths, f"Missing endpoint: {p}"


def test_admin_nodes_endpoints_present(openapi_schema):
    paths = set(openapi_schema["paths"].keys())
    for p in (
        "/api/admin/nodes",
        "/api/admin/nodes/{node_id}",
        "/api/admin/nodes/{node_id}/role",
        "/api/admin/nodes/{node_id}/shutdown",
        "/api/admin/nodes/{node_id}/ping",
        "/api/admin/nodes/{node_id}/diagnostics",
        "/api/admin/nodes/{node_id}/restart",
    ):
        assert p in paths, f"Missing endpoint: {p}"


def test_security_scheme_defined(openapi_schema):
    schemes = (openapi_schema.get("components", {})
               .get("securitySchemes", {}))
    assert "BasicAuth" in schemes
    assert schemes["BasicAuth"]["type"] == "http"
    assert schemes["BasicAuth"]["scheme"] == "basic"
