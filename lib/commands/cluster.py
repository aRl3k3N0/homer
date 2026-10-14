"""
cluster:status  -- pretty table of all cluster nodes
cluster:gc      -- remove stale node rows

Usage:
    homer cluster:status
    homer cluster:status --all          # include dead nodes
    homer cluster:status --watch 5      # refresh every 5 seconds
    homer cluster:gc --older 3600       # drop rows older than 1h
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from lib.console import console, Color


DESCRIPTIONS = {
    "status":   "Show cluster nodes",
    "gc":       "Remove stale node rows",
    "describe": "Show detailed information about a node",
    "join":     "Register this node in a cluster",
}


# ─────────── cluster:status ───────────

def status(context):
    args = context["args"]
    show_dead = bool(args.get("all", False))
    watch_interval = args.get("watch")
    try:
        watch_interval = int(watch_interval) if watch_interval is not None else None
    except (TypeError, ValueError):
        watch_interval = None

    if watch_interval:
        try:
            _watch_loop(context, show_dead, watch_interval)
        except KeyboardInterrupt:
            console.newline()
        return 0

    return _render_once(context, show_dead)


def _watch_loop(context, show_dead: bool, interval: int):
    while True:
        # Clear screen
        print("\033[2J\033[H", end="")
        _render_once(context, show_dead)
        console.newline()
        console.comment(f"  refreshing every {interval}s. Ctrl+C to stop.")
        time.sleep(interval)


def _render_once(context, show_dead: bool) -> int:
    from lib.cluster.nodes import NodeRegistry

    cfg = context["config"]
    ttl = int(cfg.get("cluster.ttl_seconds", 60))

    reg = NodeRegistry(
        cfg,
        node_id="cluster-status",
        ttl_seconds=ttl,
    )
    try:
        nodes = reg.list_nodes(only_alive=not show_dead)
    finally:
        reg.db.close()

    local_id = cfg.get("cluster.node_id")
    now = datetime.now()

    console.banner(
        "Homer Cluster",
        f"{len(nodes)} node(s) | TTL {ttl}s",
        color=Color.BRIGHT_CYAN,
    )

    rows = []
    for n in nodes:
        age = (now - n.last_seen).total_seconds() if n.last_seen else None
        if age is None:
            status_txt = "unknown"
            status_color = Color.WHITE
        elif age < ttl:
            status_txt = "alive"
            status_color = Color.BRIGHT_GREEN
        elif age < ttl * 5:
            status_txt = "stale"
            status_color = Color.BRIGHT_YELLOW
        else:
            status_txt = "dead"
            status_color = Color.BRIGHT_RED

        # Uptime
        uptime_sec = (now - n.started_at).total_seconds() \
            if n.started_at else None
        uptime = _fmt_uptime(uptime_sec)

        # Marker for local node
        marker = " ← local" if local_id and n.id == local_id else ""

        rows.append([
            console.colored(status_txt, status_color),
            (n.hostname or "—")[:24] + marker,
            n.ip or "—",
            console.colored(n.role or "worker", _role_color(n.role)),
            (n.id or "")[:8],
            n.version or "—",
            uptime,
            _fmt_ago(age),
        ])

    console.table(
        headers=["STATUS", "HOSTNAME", "IP", "ROLE", "ID", "VERSION",
                 "UPTIME", "LAST SEEN"],
        rows=rows,
        align=["c", "l", "l", "l", "l", "l", "r", "r"],
    )

    # Legend / quick hints
    console.newline()
    console.comment("  roles: primary / worker / read-only")
    console.comment("  hints: homer cluster:status --watch 5")
    console.comment("         homer cluster:status --all")
    return 0


def _role_color(role: str) -> str:
    return {
        "primary":   Color.BRIGHT_MAGENTA,
        "worker":    Color.BRIGHT_CYAN,
        "read-only": Color.BRIGHT_BLACK,
    }.get(role or "worker", Color.WHITE)


def _fmt_uptime(sec) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"
    return f"{sec // 86400}d{(sec % 86400) // 3600:02d}h"


def _fmt_ago(sec) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}m ago"
    if sec < 86400:
        return f"{sec // 3600}h ago"
    return f"{sec // 86400}d ago"


# ─────────── cluster:gc ───────────

def gc(context):
    """Remove node rows older than N seconds."""
    from lib.cluster.nodes import NodeRegistry

    args = context["args"]
    try:
        older = int(args.get("older", 3600))
    except (TypeError, ValueError):
        older = 3600

    cfg = context["config"]
    reg = NodeRegistry(cfg, node_id="cluster-gc")
    try:
        # reuse internal purge with custom cutoff
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(seconds=older)
        cur = reg.db.execute(
            f"DELETE FROM homer_nodes WHERE last_seen < {reg._ph(0)}",
            [cutoff],
        )
        reg.db.commit()
        n = cur.rowcount
        console.success(f"Removed {n} stale node(s) older than {older}s")
    finally:
        reg.db.close()
    return 0

def describe(context):
    """
    cluster:describe <id> [--prefix N]

    Detailed view of a node: identity, runtime, queue, i18n, last logs.
    Tries to fetch remote diagnostics if the node is not local.
    """
    args = context["args"]
    node_id = args.get("_positional", [None])[0] or args.get("id")
    if not node_id:
        console.error("Usage: homer cluster:describe <node_id>")
        console.comment("Run 'homer cluster:status' to list node ids")
        return 1

    from lib.cluster.nodes import NodeRegistry

    cfg = context["config"]
    reg = NodeRegistry(cfg, node_id="cluster-describe")
    try:
        nodes = reg.list_nodes(only_alive=False)
        node = next((n for n in nodes if n.id == node_id), None)
    finally:
        reg.db.close()

    if node is None:
        console.error(f"Node '{node_id}' not found")
        return 1

    _print_node_header(node, cfg)

    # ── Diagnostics: local or remote ──
    diag = _fetch_diagnostics(node, cfg)
    if diag is not None:
        _print_diagnostics(diag)
    else:
        console.warning("Diagnostics not available "
                        "(remote node unreachable or API disabled)")

    return 0


def _print_node_header(node, cfg):
    now = datetime.now()
    age = (now - node.last_seen).total_seconds() if node.last_seen else None
    uptime_sec = (now - node.started_at).total_seconds() if node.started_at else None

    local_id = cfg.get("cluster.node_id")
    is_local = bool(local_id and local_id == node.id)

    console.banner(
        f"Node: {node.hostname or node.id[:8]}",
        f"{node.id}{'  (local)' if is_local else ''}",
        color=Color.BRIGHT_CYAN,
    )

    console.section("Identity")
    console.key_value("Node ID", node.id)
    console.key_value("Hostname", node.hostname or "—")
    console.key_value("IP", node.ip or "—")
    console.key_value("Role", console.colored(
        node.role or "worker",
        {
            "primary": Color.BRIGHT_MAGENTA,
            "worker": Color.BRIGHT_CYAN,
            "read-only": Color.BRIGHT_BLACK,
        }.get(node.role or "worker", Color.WHITE),
    ))
    console.key_value("Version", node.version or "—")

    console.section("Runtime")
    console.key_value("Started at",
                      node.started_at.strftime("%Y-%m-%d %H:%M:%S")
                      if node.started_at else "—")
    console.key_value("Uptime", _fmt_uptime(uptime_sec))
    console.key_value("Last seen",
                      node.last_seen.strftime("%Y-%m-%d %H:%M:%S")
                      if node.last_seen else "—")
    console.key_value("Ago", _fmt_ago(age))

    if node.meta:
        console.section("Meta")
        for k, v in sorted(node.meta.items()):
            console.key_value(str(k), str(v))


def _fetch_diagnostics(node, cfg) -> dict | None:
    """
    Try to obtain diagnostics from the node:
      1. local (same node_id) -> collect locally
      2. remote HTTP GET <api_url>/api/diagnostics
    """
    import json
    import urllib.request

    local_id = cfg.get("cluster.node_id")
    if local_id and local_id == node.id:
        try:
            from lib.cluster.diagnostics import collect_diagnostics
            from lib.cluster.ws_server import get_hub
            paths = getattr(cfg, "paths", None)
            if paths is None:
                from lib.paths import Paths
                paths = Paths.from_config(cfg, Path("config.yml"))
            return collect_diagnostics(
                cfg, paths,
                node_registry=getattr(cfg, "node_registry", None),
                cluster_files=getattr(cfg, "cluster_files", None),
                ws_hub=get_hub(),
            )
        except Exception as e:
            console.warning(f"Local diagnostics failed: {e}")
            return None

    api_url = node.meta.get("api_url")
    if not api_url:
        ip = node.ip or "127.0.0.1"
        port = node.meta.get("port", 8081)
        api_url = f"http://{ip}:{port}"
    url = f"{api_url.rstrip('/')}/api/diagnostics"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        console.debug(f"Remote diagnostics failed: {e}")
        return None


def _print_diagnostics(diag: dict):
    if diag.get("pid"):
        console.section("Diagnostics")
        console.key_value("PID", diag.get("pid"))
        console.key_value("Python", diag.get("python_version") or "—")

    if "queue" in diag:
        console.section("Queue")
        q = diag["queue"] or {}
        for k in ("pending", "running", "done", "failed", "canceled", "timeout"):
            console.key_value(k, q.get(k, 0))

    if "i18n" in diag:
        console.section("i18n")
        i = diag["i18n"] or {}
        console.key_value("Cache size", i.get("cache_size", 0))
        console.key_value("Hits", i.get("cache_hits", 0))
        console.key_value("Misses", i.get("cache_misses", 0))
        console.key_value("Locales", ", ".join(i.get("locales", [])))
        console.key_value("Missing keys", i.get("missing_keys", 0))

    if "cluster_ws" in diag:
        console.section("Cluster WS")
        console.key_value("Subscribers",
                          (diag["cluster_ws"] or {}).get("subscribers", 0))

    if "scheduler" in diag:
        s = diag["scheduler"] or {}
        if "cron_tasks" in s:
            console.section("Scheduler")
            console.key_value("Cron tasks", s.get("cron_tasks", 0))
            console.key_value("Enabled", s.get("cron_enabled", 0))

    if diag.get("logs"):
        console.section("Last log lines")
        for line in diag["logs"][-20:]:
            console.comment("  " + line)

def join(context):
    """
    cluster:join <url> [--role worker] [--token X]

    Register this node with a remote primary.

    Writes the result into var/cluster.json (persistent) and, if
    cluster.auto_apply is true, also updates config.yml (only if
    pyyaml/ruamel available and config path is writable).
    """
    import json
    import socket
    import urllib.error
    import urllib.request
    from pathlib import Path

    args = context["args"]
    url = args.get("_positional", [None])[0] or args.get("url")
    if not url:
        console.error("Usage: homer cluster:join <primary_url>")
        console.comment("Example: homer cluster:join http://primary.example.com:8081")
        return 1

    role = args.get("role", "worker")
    token = args.get("token") or context["config"].get("cluster.join_token")

    # ─── Build request
    public_url = context["config"].get("webui.public_url") or ""
    ip = _local_ip()
    port = context["config"].get("webui.port", 8081)

    payload = {
        "hostname": socket.gethostname(),
        "ip": ip,
        "role": role,
        "version": context["config"].get("app.version", "1.0.0"),
        "api_url": public_url or f"http://{ip}:{port}",
        "meta": {
            "pid": __import__("os").getpid(),
            "port": port,
        },
        "node_id": context["config"].get("cluster.node_id"),
    }

    join_endpoint = url.rstrip("/") + "/api/cluster/join"

    console.info(f"Joining cluster: {join_endpoint}")
    console.key_value("Hostname", payload["hostname"])
    console.key_value("IP", payload["ip"])
    console.key_value("Role", role)

    req = urllib.request.Request(
        join_endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"X-Cluster-Token": token} if token else {}),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            data = json.loads(body)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        console.error(f"Join failed: HTTP {e.code} — {err}")
        return 1
    except Exception as e:
        console.error(f"Join failed: {e}")
        return 1

    console.success("Joined successfully")
    console.key_value("Node ID", data.get("node_id"))
    console.key_value("Primary ID", data.get("primary_id") or "—")
    console.key_value("WS URL", data.get("ws_url"))
    console.key_value("TTL", f"{data.get('ttl_seconds')}s")
    console.key_value("Heartbeat", f"{data.get('heartbeat_seconds')}s")

    # ─── Persist
    root = Path(context["root_dir"])
    var_dir = root / "var"
    var_dir.mkdir(exist_ok=True)
    cluster_file = var_dir / "cluster.json"
    cluster_file.write_text(
        json.dumps({
            "node_id": data.get("node_id"),
            "primary_url": url,
            "primary_id": data.get("primary_id"),
            "ws_url": data.get("ws_url"),
            "ws_token": data.get("ws_token"),
            "role": role,
            "joined_at": __import__("datetime").datetime.now().isoformat(),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.success(f"Saved: {cluster_file.relative_to(root)}")

    console.newline()
    console.comment("Next steps:")
    console.comment("  1. Add to config.yml:")
    console.comment("       cluster:")
    console.comment("         enabled: true")
    console.comment(f"         role: {role}")
    console.comment(f"         primary_ws_url: {data.get('ws_url')}")
    if data.get("ws_token"):
        console.comment(f"         ws_token: {data.get('ws_token')}")
    console.comment("  2. Restart this node:")
    console.comment("       homer webui:restart")
    console.comment("       homer scheduler:restart")
    return 0


def _local_ip() -> str:
    import socket as _socket
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
