"""
Node diagnostics: a snapshot of runtime state of the current node.

Used by /api/admin/nodes/{id}/diagnostics on the node itself and by
remote callers (from /admin/nodes) to see what's happening.

Endpoints are local; each node exposes them under its own API.
"""

from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def _node_id_from_config(config) -> Optional[str]:
    return config.get("cluster.node_id")


def collect_diagnostics(config, paths, logger=None,
                        node_registry=None, cluster_files=None,
                        ws_hub=None) -> dict[str, Any]:
    """
    Build a diagnostics dictionary for the current node.
    All pieces are optional -- missing ones are reported as None.
    """
    result: dict[str, Any] = {
        "ts": datetime.now().isoformat(),
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "python_version": _python_version(),
    }

    # ─── Node ───
    if node_registry is not None:
        try:
            result["node_id"] = node_registry.node_id
            result["role"] = node_registry.role
            result["started_at"] = None
            nodes = node_registry.list_nodes(only_alive=False)
            for n in nodes:
                if n.id == node_registry.node_id:
                    result["started_at"] = (
                        n.started_at.isoformat() if n.started_at else None
                    )
                    break
        except Exception as e:
            result["node_error"] = str(e)

    # ─── Queue ───
    try:
        from homer.queue import QueueStorage
        qs = QueueStorage(config)
        try:
            result["queue"] = qs.stats()
        finally:
            qs.close()
    except Exception as e:
        result["queue_error"] = str(e)

    # ─── i18n ───
    try:
        from homer.i18n import get_i18n
        i18n = get_i18n()
        stats = i18n.cache_stats()
        result["i18n"] = {
            "cache_size": stats.get("size", 0),
            "cache_hits": stats.get("hits", 0),
            "cache_misses": stats.get("misses", 0),
            "locales": i18n.available_locales(),
            "missing_keys": len(i18n.missing_keys()),
        }
    except Exception as e:
        result["i18n_error"] = str(e)

    # ─── Cluster WS ───
    if ws_hub is not None:
        try:
            result["cluster_ws"] = {
                "subscribers": ws_hub.count,
            }
        except Exception as e:
            result["cluster_ws_error"] = str(e)

    # ─── Cluster files ───
    if cluster_files is not None:
        try:
            result["cluster_files"] = {
                "role": cluster_files.role,
                "last_change_id": cluster_files._last_change_id,
            }
        except Exception:
            pass

    # ─── Last N log lines ───
    try:
        result["logs"] = _tail_logs(paths, logger, n=50)
    except Exception as e:
        result["logs_error"] = str(e)

    # ─── Scheduler state ───
    try:
        result["scheduler"] = _scheduler_state(config)
    except Exception as e:
        result["scheduler_error"] = str(e)

    return result


def _python_version() -> str:
    import sys
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _tail_logs(paths, logger, n: int = 50) -> list[str]:
    """Read the last N lines from the most recently modified log file."""
    logs_dir = paths.log_dir
    if not logs_dir.exists():
        return []
    latest = None
    latest_mtime = 0.0
    for p in logs_dir.rglob("*.log"):
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt > latest_mtime:
            latest_mtime = mt
            latest = p
    if latest is None:
        return []
    try:
        with open(latest, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-n:]]
    except Exception:
        return []


def _scheduler_state(config) -> dict:
    """Basic scheduler / queue counters."""
    out = {}
    try:
        from homer.queue import QueueStorage
        qs = QueueStorage(config)
        try:
            out["queue"] = qs.stats()
        finally:
            qs.close()
    except Exception:
        pass

    try:
        from homer.scheduler import create_storage
        st = create_storage(config)
        try:
            tasks = st.list()
            out["cron_tasks"] = len(tasks)
            out["cron_enabled"] = sum(1 for t in tasks if t.enabled)
        finally:
            st.close()
    except Exception:
        pass

    return out
