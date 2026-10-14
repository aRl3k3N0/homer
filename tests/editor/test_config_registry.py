"""
Tests for ConfigRegistry: sections, leaves, set/delete, rename.
"""
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def registry(tmp_path):
    from lib.config import Config
    from lib.paths import Paths
    from lib.editor.config_registry import ConfigRegistry

    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(textwrap.dedent("""
        app:
          name: Homer
          version: 1.0.0

        databases:
          postgres:
            host: localhost
            port: 5432
          oracle:
            host: oracle.local
            port: 1521

        logging:
          level: INFO
    """).strip() + "\n", encoding="utf-8")

    cfg = Config(cfg_file)
    paths = Paths.from_config(cfg, cfg_file)
    return ConfigRegistry(cfg, paths)


def test_list_sections(registry):
    sections = registry.list_sections()
    assert "" in sections
    assert "app" in sections
    assert "databases" in sections
    assert "databases.postgres" in sections
    assert "databases.oracle" in sections
    assert "logging" in sections


def test_list_leaves_of_section(registry):
    leaves = registry.list_leaves_of("app")
    paths = sorted(e.path for e in leaves)
    assert paths == ["app.name", "app.version"]


def test_list_root_leaves_empty(registry):
    """No leaves directly in root for this layout."""
    assert registry.list_leaves_of("") == []


def test_get_value(registry):
    e = registry.get("app.name")
    assert e is not None
    assert e.value == "Homer"
    assert e.type == "string"


def test_get_missing(registry):
    assert registry.get("no.such.key") is None


def test_set_updates_file(registry, tmp_path):
    registry.set("app.version", "2.0.0")
    new_cfg = (tmp_path / "config.yml").read_text(encoding="utf-8")
    assert "2.0.0" in new_cfg
    assert "1.0.0" not in new_cfg


def test_set_nested(registry):
    registry.set("databases.postgres.port", 5433)
    e = registry.get("databases.postgres.port")
    assert e.value == 5433


def test_set_with_expected_value_ok(registry):
    registry.set("app.name", "Homer2", expected_value="Homer")
    assert registry.get("app.name").value == "Homer2"


def test_set_with_wrong_expected_value_raises(registry):
    from lib.editor.config_registry import ConfigRegistryError
    with pytest.raises(ConfigRegistryError):
        registry.set("app.name", "X", expected_value="not-the-current")


def test_delete(registry):
    registry.delete("app.version")
    assert registry.get("app.version") is None


def test_create_value(registry):
    registry.create_value("app.env", "production")
    assert registry.get("app.env").value == "production"


def test_create_value_existing_raises(registry):
    from lib.editor.config_registry import ConfigRegistryError
    with pytest.raises(ConfigRegistryError):
        registry.create_value("app.name", "dup")


def test_create_section(registry):
    registry.create_section("cache")
    assert "cache" in registry.list_sections()


def test_delete_empty_section(registry):
    registry.create_section("empty_section")
    registry.delete_section("empty_section")
    assert "empty_section" not in registry.list_sections()


def test_delete_nonempty_section_raises(registry):
    from lib.editor.config_registry import ConfigRegistryError
    with pytest.raises(ConfigRegistryError):
        registry.delete_section("app")


def test_rename_value(registry):
    registry.rename("app.version", "app.app_version")
    assert registry.get("app.version") is None
    assert registry.get("app.app_version") is not None


def test_rename_to_existing_raises(registry):
    from lib.editor.config_registry import ConfigRegistryError
    with pytest.raises(ConfigRegistryError):
        registry.rename("app.version", "app.name")
