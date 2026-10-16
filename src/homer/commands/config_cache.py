"""
config:cache   -- build the config cache
config:clear   -- remove the config cache
config:info    -- show cache info
config:rebuild -- alias for cache
"""

from __future__ import annotations

from pathlib import Path

from homer.core.console import console, Color


DESCRIPTIONS = {
    "cache":   "Build the config cache (merged YAML with includes)",
    "rebuild": "Rebuild the config cache from scratch",
    "clear":   "Remove the config cache file",
    "info":    "Show config cache information",
}


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def cache(context):
    """Build config cache: full merge of config.yml + includes."""
    cfg = context["config"]

    console.section("Building config cache")

    try:
        cfg.build_cache()
    except Exception as e:
        console.error(f"Failed to build config cache: {e}")
        return 1

    info = cfg.cache_info()
    console.success("Config cache built")
    console.key_value("Path", info["path"])
    console.key_value("Size", _fmt_bytes(info.get("size", 0)))
    console.key_value("Source files", info.get("source_files", 0))
    console.key_value("Generated", info.get("generated_at") or "—")

    # Show what sources were merged
    if cfg.source_files:
        console.section("Source files")
        for p in cfg.source_files:
            try:
                rel = p.relative_to(Path(context["root_dir"]))
                console.list_item(str(rel))
            except ValueError:
                console.list_item(str(p))
    return 0


def rebuild(context):
    """Alias for cache."""
    return cache(context)


def clear(context):
    """Remove the config cache file."""
    cfg = context["config"]
    if cfg.clear_cache():
        console.success("Config cache cleared.")
        return 0
    console.comment("Nothing to clear.")
    return 0


def info(context):
    """Show config cache info."""
    cfg = context["config"]
    ci = cfg.cache_info()

    console.banner("Config cache", "merged YAML with includes")

    if not ci.get("exists"):
        console.warning("Cache does not exist.")
        console.key_value("Expected path", ci["path"])
        console.comment("Run 'homer config:cache' to build it.")
        return 0

    console.key_value("Path", ci["path"])
    console.key_value("Size", _fmt_bytes(ci.get("size", 0)))
    console.key_value("Generated", ci.get("generated_at") or "—")
    console.key_value("Source files", ci.get("source_files", 0))
    console.key_value(
        "Fresh",
        console.colored("yes", Color.BRIGHT_GREEN) if ci.get("fresh")
        else console.colored("stale", Color.BRIGHT_YELLOW),
    )
    return 0
