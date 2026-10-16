"""
Tests for ClusterFiles: write, delete, apply, initial_sync.
"""
import pytest
from datetime import datetime


@pytest.fixture
def cluster_files(cluster_config, tmp_path):
    from homer.core.paths import Paths
    from homer.cluster.files import ClusterFiles

    # Materialize a real Paths object
    paths = Paths.from_config(cluster_config, tmp_path / "config.yml")
    paths.ensure_all()

    cf = ClusterFiles(
        cluster_config,
        node_id="node-a",
        paths=paths,
        role="primary",
    )
    yield cf
    try:
        cf.stop_watcher()
    except Exception:
        pass
    try:
        cf.db.close()
    except Exception:
        pass


def test_write_creates_db_row_and_local_file(cluster_files, tmp_path):
    cluster_files.write("config", "app.yml", "name: Homer\n", author="tester")

    # DB row
    row = cluster_files.db.fetchone(
        f"SELECT checksum, version, content FROM homer_files "
        f"WHERE path = {cluster_files._ph(0)}",
        ["config:app.yml"],
        dictionary=True,
    )
    assert row is not None
    assert row["version"] == 1

    # Local file
    p = cluster_files.paths.config_path.parent / "app.yml"
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "name: Homer\n"


def test_write_increments_version(cluster_files):
    cluster_files.write("config", "a.yml", "x: 1\n", author="u")
    cluster_files.write("config", "a.yml", "x: 2\n", author="u")

    row = cluster_files.db.fetchone(
        f"SELECT version FROM homer_files WHERE path = {cluster_files._ph(0)}",
        ["config:a.yml"], dictionary=True,
    )
    assert row["version"] == 2


def test_delete_removes_row_and_file(cluster_files):
    cluster_files.write("config", "a.yml", "x: 1\n", author="u")
    p = cluster_files.paths.config_path.parent / "a.yml"
    assert p.exists()

    cluster_files.delete("config", "a.yml", author="u")
    assert not p.exists()

    row = cluster_files.db.fetchone(
        f"SELECT 1 FROM homer_files WHERE path = {cluster_files._ph(0)}",
        ["config:a.yml"],
    )
    assert row is None


def test_change_record_written(cluster_files):
    cluster_files.write("config", "a.yml", "x: 1\n", author="alice")
    rows = cluster_files.db.fetchall(
        "SELECT path, action, author FROM homer_changes",
        dictionary=True,
    )
    assert any(r["path"] == "config:a.yml"
               and r["action"] == "write"
               and r["author"] == "alice"
               for r in rows)


def test_apply_change_writes_local_file(cluster_files):
    # Simulate a remote write: insert into DB, then apply
    cluster_files.db.execute(
        f"INSERT INTO homer_files "
        f"(path, category, checksum, content, version, updated_at, updated_by) "
        f"VALUES ({cluster_files._ph(0)}, {cluster_files._ph(1)}, "
        f"{cluster_files._ph(2)}, {cluster_files._ph(3)}, "
        f"{cluster_files._ph(4)}, {cluster_files._ph(5)}, "
        f"{cluster_files._ph(6)})",
        ["config:remote.yml", "config", "x",
         b"from-remote: yes\n", 1, datetime.now(), "other"],
    )
    cluster_files.db.commit()

    cluster_files._apply_change({
        "category": "config",
        "rel_path": "remote.yml",
        "action": "write",
    })
    p = cluster_files.paths.config_path.parent / "remote.yml"
    assert p.exists()
    assert "from-remote" in p.read_text(encoding="utf-8")


def test_apply_change_no_op_when_unchanged(cluster_files):
    """Writing same content twice should not touch file mtime."""
    cluster_files.write("config", "same.yml", "x: 1\n", author="u")
    p = cluster_files.paths.config_path.parent / "same.yml"
    m1 = p.stat().st_mtime

    cluster_files._apply_change({
        "category": "config",
        "rel_path": "same.yml",
        "action": "write",
    })
    m2 = p.stat().st_mtime
    assert m1 == m2


def test_apply_change_delete(cluster_files):
    cluster_files.write("config", "del.yml", "x: 1\n", author="u")
    p = cluster_files.paths.config_path.parent / "del.yml"
    assert p.exists()

    cluster_files._apply_change({
        "category": "config",
        "rel_path": "del.yml",
        "action": "delete",
    })
    assert not p.exists()


def test_max_change_id(cluster_files):
    assert cluster_files._max_change_id() == 0
    cluster_files.write("config", "a.yml", "x: 1\n", author="u")
    assert cluster_files._max_change_id() >= 1


def test_poll_changes_returns_only_new(cluster_files):
    cluster_files.write("config", "a.yml", "x: 1\n", author="u")
    changes = cluster_files._poll_changes()
    assert len(changes) >= 1

    # Second poll returns nothing new
    changes2 = cluster_files._poll_changes()
    assert changes2 == []
