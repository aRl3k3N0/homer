"""
i18n:cache   -- build the translations cache (pickle)
i18n:clear   -- remove the translations cache
i18n:info    -- show cache info and layer sources
i18n:rebuild -- alias for cache
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime
from pathlib import Path

from lib.console import console, Color
from lib.i18n.manager import Layer


DESCRIPTIONS = {
    "cache":   "Build the translations cache (pickle)",
    "rebuild": "Rebuild the translations cache from scratch",
    "clear":   "Remove the translations cache",
    "info":    "Show translations cache information and sources",
}

CACHE_VERSION = 1


def _cache_dir(context) -> Path:
    paths = context.get("paths")
    if paths:
        return paths.cache_dir / "i18n"
    return Path(context["root_dir"]) / "var" / "cache" / "i18n"


def _langs_dirs(context) -> list[Path]:
    """
    Collect every directory that contributes translations, in layer
    order: system, project, plugin.
    """
    root = Path(context["root_dir"])
    dirs: list[Path] = []

    # 1) System
    sys_langs = root / "lib" / "webui" / "i18n"
    if sys_langs.exists():
        dirs.append(sys_langs)

    # 2) Project
    paths = context.get("paths")
    if paths and paths.langs_dir.exists():
        dirs.append(paths.langs_dir)
    elif (root / "langs").exists():
        dirs.append(root / "langs")

    # 3) Plugins
    try:
        from lib.plugins import get_manager
        for p in get_manager().list():
            if p.langs_dir:
                dirs.append(p.langs_dir)
    except Exception:
        pass

    return dirs


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def cache(context):
    import yaml

    console.section("Building i18n cache")

    dirs = _langs_dirs(context)
    if not dirs:
        console.warning("No langs directories found.")
        return 1

    cache_dir = _cache_dir(context)
    cache_dir.mkdir(parents=True, exist_ok=True)

    merged: dict[str, dict] = {}
    files_meta: list[dict] = []

    def deep_merge(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                deep_merge(dst[k], v)
            else:
                dst[k] = v

    # Load in layer order (weakest first)
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

    for locale, data in merged.items():
        p = cache_dir / f"{locale}.pickle"
        with open(p, "wb") as fp:
            pickle.dump(data, fp, protocol=pickle.HIGHEST_PROTOCOL)

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
    cache_dir = _cache_dir(context)
    meta_path = cache_dir / "meta.json"

    console.banner("i18n cache", "translations")

    if not meta_path.exists():
        console.warning("Cache does not exist.")
        console.key_value("Expected path", str(cache_dir))
        console.comment("Run 'homer i18n:cache' to build it.")
    else:
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

    # Sources by layer
    console.section("Sources by layer")
    try:
        from lib.i18n import get_i18n
        i18n = get_i18n()
        src = i18n.sources()
        for layer in Layer.ORDER:
            paths = src.get(layer, [])
            if not paths:
                continue
            console.print(console.colored(f"  {layer}", Color.BOLD))
            for p in paths:
                console.list_item(str(p))
    except Exception:
        pass

    return 0
