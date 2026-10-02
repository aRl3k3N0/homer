"""
registry:cache    -- build registry cache (metadata for commands and plugins)
registry:rebuild  -- alias for cache (full rescan + save)
registry:clear    -- remove cache file
registry:info     -- show cache stats
registry:bench    -- benchmark cached vs. uncached loading
"""

from __future__ import annotations

import time
from pathlib import Path

from lib.console import console, Color
from lib.registry_cache import RegistryCache


DESCRIPTIONS = {
    "cache":   "Build registry cache (commands and plugins metadata)",
    "rebuild": "Rebuild registry cache from scratch",
    "clear":   "Remove registry cache file",
    "info":    "Show registry cache information",
    "bench":   "Benchmark cached vs. uncached loading",
}


def _make_cache(context) -> RegistryCache:
    cfg = context["config"]
    root = Path(context["root_dir"])
    return RegistryCache(
        root,
        enabled=True,
        cache_path=root / cfg.get("registry.cache_path", "var/cache/registry.json"),
    )


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


# ─────────── cache / rebuild ───────────

def cache(context):
    """Build the registry cache."""
    root = Path(context["root_dir"])
    cfg = context["config"]
    cache_obj = _make_cache(context)

    console.section("Building registry cache")

    started = time.perf_counter()

    from lib.command_loader import CommandLoader
    from lib.plugins import get_manager

    pm = get_manager()
    pm.discover(root / "plugins", cfg, use_cache=False)
    pm.load_all({"config": cfg, "root_dir": root})

    loader = CommandLoader(root / "commands", root_dir=root)
    for p in pm.list():
        if p.commands_dir:
            loader.add_plugin_commands(p.name, p.commands_dir)

    commands = loader.load_commands()

    # Filter out entries without a filesystem path (built-ins)
    cache_commands = {
        name: info
        for name, info in commands.items()
        if info.get("path")
    }

    langs_dirs = [root / "langs"]
    for p in pm.list():
        if p.langs_dir:
            langs_dirs.append(p.langs_dir)

    snapshot = cache_obj.build_snapshot(
        commands=cache_commands,
        plugins=list(pm.list()),
        langs_dirs=langs_dirs,
    )
    cache_obj.save(snapshot)

    elapsed = (time.perf_counter() - started) * 1000
    console.success(f"Registry cache built in {elapsed:.1f} ms")
    console.key_value("Path", str(cache_obj.cache_path))
    console.key_value("Commands", len(cache_commands))
    console.key_value("Plugins", len(pm.list()))
    return 0


def rebuild(context):
    """Alias for cache (kept for symmetry with other :rebuild commands)."""
    return cache(context)


# ─────────── clear ───────────

def clear(context):
    """Remove the cache file."""
    cache_obj = _make_cache(context)
    if cache_obj.clear():
        console.success("Registry cache cleared.")
        return 0
    console.comment("Nothing to clear.")
    return 0


# ─────────── info ───────────

def info(context):
    """Show cache stats."""
    cache_obj = _make_cache(context)
    stats = cache_obj.stats()

    console.banner("Registry cache", "commands and plugins metadata")

    if not stats["exists"]:
        console.warning("Cache does not exist.")
        console.key_value("Expected path", stats["path"])
        console.comment("Run 'homer registry:cache' to build it.")
        return 0

    console.key_value("Path", stats["path"])
    console.key_value("Size", _fmt_bytes(stats["size"]))
    console.key_value("Generated", stats.get("generated_at") or "—")
    console.key_value("Homer version", stats.get("homer_version") or "—")
    console.key_value("Commands", stats.get("commands", 0))
    console.key_value("Plugins", stats.get("plugins", 0))
    console.key_value("Files tracked", stats.get("files_tracked", 0))

    fresh = stats.get("fresh", False)
    console.key_value(
        "Fresh",
        console.colored("yes", Color.BRIGHT_GREEN) if fresh
        else console.colored("stale", Color.BRIGHT_YELLOW),
    )
    return 0


# ─────────── bench ───────────

def bench(context):
    """Benchmark fresh scan vs. cache hit."""
    root = Path(context["root_dir"])
    cfg = context["config"]

    from lib.command_loader import CommandLoader
    from lib.plugins import get_manager

    # Full scan first
    console.section("1/2  Full scan (no cache)")

    cache_obj = _make_cache(context)
    cache_obj.clear()

    t0 = time.perf_counter()
    pm = get_manager()
    pm.discover(root / "plugins", cfg, use_cache=False)
    pm.load_all({"config": cfg, "root_dir": root})

    loader = CommandLoader(root / "commands", root_dir=root)
    for p in pm.list():
        if p.commands_dir:
            loader.add_plugin_commands(p.name, p.commands_dir)
    commands_eager = loader.load_commands()
    elapsed_eager = (time.perf_counter() - t0) * 1000
    console.success(f"Full scan: {elapsed_eager:.1f} ms "
                    f"({len(commands_eager)} commands)")

    # Save snapshot
    cache_commands = {n: i for n, i in commands_eager.items() if i.get("path")}
    langs_dirs = [root / "langs"]
    for p in pm.list():
        if p.langs_dir:
            langs_dirs.append(p.langs_dir)
    cache_obj.save(cache_obj.build_snapshot(
        commands=cache_commands,
        plugins=list(pm.list()),
        langs_dirs=langs_dirs,
    ))

    # Cache hit path
    console.section("2/2  Cache hit")

    t0 = time.perf_counter()
    cached = cache_obj.load()
    if not cached or not cache_obj.is_fresh(cached):
        console.error("Cache is not fresh -- cannot benchmark cache hit.")
        return 1

    pm2 = get_manager()
    pm2._plugins.clear()
    pm2._initialized.clear()
    pm2.discover(root / "plugins", cfg, use_cache=True)

    loader2 = CommandLoader(root / "commands", root_dir=root)
    for p in pm2.list():
        if p.commands_dir:
            loader2.add_plugin_commands(p.name, p.commands_dir)

    commands_lazy = {}
    for name, item in (cached.get("commands") or {}).items():
        commands_lazy[name] = {
            "path": root / item["path"],
            "description": item.get("description", ""),
            "source": item.get("source", "user"),
            "lazy": True,
            "module": None,
            "execute": None,
        }
    elapsed_cache = (time.perf_counter() - t0) * 1000
    console.success(f"Cache hit: {elapsed_cache:.1f} ms "
                    f"({len(commands_lazy)} commands)")

    console.newline()
    console.section("Result")
    speedup = elapsed_eager / elapsed_cache if elapsed_cache > 0 else 0
    console.key_value("Full scan", f"{elapsed_eager:.1f} ms")
    console.key_value("Cache hit", f"{elapsed_cache:.1f} ms")
    console.key_value("Speedup", f"{speedup:.1f}×")
    return 0
