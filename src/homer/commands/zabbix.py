"""
zabbix:discover   -- Zabbix LLD discovery (JSON)
zabbix:metric KEY -- single metric value for Zabbix agent

Usage from Zabbix agent:

    UserParameter=homer[*],/opt/homer/homer zabbix:metric "$1"

Then items:
    homer[uptime]
    homer[queue.pending]
    homer[queue.running]
    homer[ws.subscribers]
    homer[nodes.primary]
    homer[nodes.worker]
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime

from homer.core.console import console


DESCRIPTIONS = {
    "discover": "Zabbix LLD discovery (JSON)",
    "metric":   "Single metric value for Zabbix agent",
}


# ─────────── Metric keys ───────────

def _metric_keys():
    return [
        # Node
        "node.role.primary",
        "node.role.worker",
        "node.role.read_only",
        "uptime",

        # Queue
        "queue.pending",
        "queue.running",
        "queue.done",
        "queue.failed",
        "queue.canceled",
        "queue.timeout",

        # Cluster
        "ws.subscribers",
        "nodes.total",
        "nodes.primary",
        "nodes.worker",
        "nodes.read_only",
        "files.total",
        "files.last_change_id",

        # i18n
        "i18n.cache_size",
        "i18n.cache_hits",
        "i18n.cache_misses",
        "i18n.missing_keys",
    ]


# ─────────── Value resolution ───────────

def _get_value(context, key: str):
    cfg = context["config"]

    # ─── Queue ───
    if key.startswith("queue."):
        status = key.split(".", 1)[1]
        from homer.queue import QueueStorage
        qs = QueueStorage(cfg)
        try:
            stats = qs.stats()
        finally:
            qs.close()
        return int(stats.get(status, 0))

    # ─── i18n ───
    if key.startswith("i18n."):
        from homer.i18n import get_i18n
        i18n = get_i18n()
        stats = i18n.cache_stats()
        if key == "i18n.cache_size":
            return int(stats.get("size", 0))
        if key == "i18n.cache_hits":
            return int(stats.get("hits", 0))
        if key == "i18n.cache_misses":
            return int(stats.get("misses", 0))
        if key == "i18n.missing_keys":
            return len(i18n.missing_keys())

    # ─── WS subscribers ───
    if key == "ws.subscribers":
        from homer.cluster.ws_server import get_hub
        return int(get_hub().count)

    # ─── Cluster nodes ───
    if key.startswith("nodes.") or key.startswith("node.role."):
        from homer.cluster.nodes import NodeRegistry
        reg = NodeRegistry(cfg, node_id="zabbix-probe",
                           ttl_seconds=int(cfg.get("cluster.ttl_seconds", 60)))
        try:
            nodes = reg.list_nodes(only_alive=True)
        finally:
            reg.db.close()
        total = len(nodes)
        roles = {"primary": 0, "worker": 0, "read-only": 0}
        for n in nodes:
            roles[n.role] = roles.get(n.role, 0) + 1
        if key == "nodes.total":
            return total
        if key == "nodes.primary":
            return roles.get("primary", 0)
        if key == "nodes.worker":
            return roles.get("worker", 0)
        if key == "nodes.read_only":
            return roles.get("read-only", 0)

    # ─── Uptime of the current process ───
    if key == "uptime":
        # Best-effort: read the pid file age if present
        try:
            from pathlib import Path
            pid_dir = Path(cfg.get("paths.run_dir", "var/run"))
            # Try webui pid first, then scheduler
            for name in ("webui", "schedule", "scheduler"):
                pid_file = pid_dir / f"{name}.pid"
                if pid_file.exists():
                    return int(
                        datetime.now().timestamp() - pid_file.stat().st_mtime
                    )
        except Exception:
            pass
        return 0

    # ─── Cluster files ───
    if key == "files.total":
        from homer.cluster.files import ClusterFiles
        cf = getattr(cfg, "cluster_files", None)
        if cf is None:
            return 0
        try:
            row = cf.db.fetchone("SELECT COUNT(*) AS c FROM homer_files",
                                 dictionary=True)
            return int(row["c"] if isinstance(row, dict) else row[0]) if row else 0
        except Exception:
            return 0

    if key == "files.last_change_id":
        cf = getattr(cfg, "cluster_files", None)
        if cf is None:
            return 0
        try:
            return int(cf._max_change_id())
        except Exception:
            return 0

    raise KeyError(f"unknown metric: {key}")


# ─────────── Commands ───────────

def discover(context):
    """LLD discovery for Zabbix (auto-create items)."""
    data = [
        {"{#HOMER_METRIC}": k}
        for k in _metric_keys()
    ]
    print(json.dumps({"data": data}))
    return 0


def metric(context):
    args = context["args"]
    key = args.get("_positional", [None])[0] or args.get("key")
    if not key:
        # Print usage to stderr; return exit code 1
        import sys
        print("usage: homer zabbix:metric <key>", file=sys.stderr)
        return 1

    try:
        value = _get_value(context, key)
        print(value)
        return 0
    except Exception as e:
        import sys
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
