"""
i18n:cache   -- build the translations cache (pickle)
i18n:clear   -- remove the translations cache
i18n:info    -- show cache info
i18n:rebuild -- alias for cache
i18n:check   -- verify translations (already exists, kept separate)
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime
from pathlib import Path

from lib.console import console, Color


DESCRIPTIONS = {
    "cache":   "Build the translations cache (pickle)",
    "rebuild": "Rebuild the translations cache from scratch",
    "clear":   "Remove the translations cache",
    "info":    "Show translations cache information",
}

CACHE_VERSION = 1


def _cache_dir(context) -> Path:
    return Path(context["root_dir"]) / "var" / "cache" / "i18n"


def _langs_dirs(context) -> list[Path]:
    """Collect every directory that contributes translations."""
    root = Path(context["root_dir"])
    dirs: list[Path] = [root / "langs"]

    try:
        from lib.plugins import get_manager
        pm = get_manager()
        for p in pm.list():
            if p.langs_dir:
                dirs.append(p.langs_dir)
    except Exception:
        pass

    return [d for d in dirs if d.exists()]


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def cache(context):
    """Build pickle cache for all translations."""
    import yaml

    console.section("Building i18n cache")

    dirs = _langs_dirs(context)
    if not dirs:
        console.warning("No langs directories found.")
        return 1

    cache_dir = _cache_dir(context)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Merge all locales
    merged: dict[str, dict] = {}
    files_meta: list[dict] = []

    def deep_merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                deep_merge(dst[k], v)
            else:
                dst[k] = v

    for d in dirs:
        for f in list(sorted(d.glob("*.yml"))) + list(sorted(d.glob("*.yaml"))):
            locale = f.stem
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception as e:
                console.warning(f"Skipping {f}: {e}")
                continue
            if not isinstance(data, dict):
                continue
            bucket = merged.setdefault(locale, {})
            deep_merge(bucket, data)

            st = f.stat()
            files_meta.append({
                "path": str(f),
                "mtime": st.st_mtime,
                "size": st.st_size,
            })

    if not merged:
        console.error("Nothing to cache.")
        return 1

    # Write pickle per locale
    for locale, data in merged.items():
        p = cache_dir / f"{locale}.pickle"
        with open(p, "wb") as fp:
            pickle.dump(data, fp, protocol=pickle.HIGHEST_PROTOCOL)

    # Meta file
    meta = {
        "version": CACHE_VERSION,
        "generated_at": datetime.now().isoformat(),
        "locales": sorted(merged.keys()),
        "files": files_meta,
    }
    (cache_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    console.success("i18n cache built")
    console.key_value("Path", str(cache_dir))
    console.key_value("Locales", ", ".join(sorted(merged.keys())))
    console.key_value("Source files", len(files_meta))
    return 0


def rebuild(context):
    return cache(context)


def clear(context):
    """Remove the i18n cache directory."""
    cache_dir = _cache_dir(context)
    if not cache_dir.exists():
        console.comment("Nothing to clear.")
        return 0
    try:
        for p in cache_dir.iterdir():
            p.unlink()
        cache_dir.rmdir()
        console.success("i18n cache cleared.")
        return 0
    except Exception as e:
        console.error(f"Failed to clear i18n cache: {e}")
        return 1


def info(context):
    """Show i18n cache info."""
    cache_dir = _cache_dir(context)
    meta_path = cache_dir / "meta.json"

    console.banner("i18n cache", "translations")

    if not meta_path.exists():
        console.warning("Cache does not exist.")
        console.key_value("Expected path", str(cache_dir))
        console.comment("Run 'homer i18n:cache' to build it.")
        return 0

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        console.error(f"Cannot read meta: {e}")
        return 1

    total = sum(
        (cache_dir / f"{loc}.pickle").stat().st_size
        for loc in meta.get("locales", [])
        if (cache_dir / f"{loc}.pickle").exists()
    )

    console.key_value("Path", str(cache_dir))
    console.key_value("Size", _fmt_bytes(total))
    console.key_value("Generated", meta.get("generated_at") or "—")
    console.key_value("Locales", ", ".join(meta.get("locales", [])))
    console.key_value("Source files", len(meta.get("files", [])))
    return 0
