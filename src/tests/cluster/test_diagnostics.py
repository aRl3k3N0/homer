"""
Tests for collect_diagnostics.
"""
from pathlib import Path


def test_collect_diagnostics_minimal(cluster_config, tmp_path):
    from homer.cluster.diagnostics import collect_diagnostics

    cluster_config.paths = None
    from homer.core.paths import Paths
    paths = Paths.from_config(cluster_config, tmp_path / "config.yml")
    paths.ensure_all()

    diag = collect_diagnostics(cluster_config, paths)

    assert "ts" in diag
    assert "hostname" in diag
    assert "pid" in diag
    assert "python_version" in diag


def test_collect_diagnostics_with_registry(cluster_config, registry):
    from homer.cluster.diagnostics import collect_diagnostics
    from homer.core.paths import Paths

    registry.register()
    paths = Paths.from_config(cluster_config, Path("config.yml"))
    paths.ensure_all()

    diag = collect_diagnostics(
        cluster_config, paths, node_registry=registry,
    )
    assert diag.get("node_id") == registry.node_id
    assert diag.get("role") == registry.role


def test_collect_diagnostics_includes_i18n(cluster_config, tmp_path):
    from homer.cluster.diagnostics import collect_diagnostics
    from homer.core.paths import Paths

    paths = Paths.from_config(cluster_config, tmp_path / "config.yml")
    paths.ensure_all()

    diag = collect_diagnostics(cluster_config, paths)
    assert "i18n" in diag
    assert "locales" in diag["i18n"]


def test_tail_logs_returns_last_lines(cluster_config, tmp_path):
    from homer.cluster.diagnostics import _tail_logs
    from homer.core.paths import Paths

    paths = Paths.from_config(cluster_config, tmp_path / "config.yml")
    paths.ensure_all()

    log_dir = paths.log_dir / "webui"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "2026-10-14.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(200)) + "\n",
                        encoding="utf-8")

    lines = _tail_logs(paths, logger=None, n=10)
    assert len(lines) == 10
    assert lines[-1] == "line 199"
