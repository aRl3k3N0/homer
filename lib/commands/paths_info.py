"""
paths:info -- show resolved paths for the current config.

Prints every path, its value, and where it came from:
    default  /  config.yml  /  env var
"""

from pathlib import Path

from lib.console import console, Color

DESCRIPTION = "Show resolved paths and their origin"


def execute(context):
    paths = context.get("paths")
    if paths is None:
        console.error("No resolved paths in context.")
        return 1

    console.banner("Resolved paths", f"base = {paths.base}")

    rows = []
    for key, value in paths.as_dict().items():
        if key == "base":
            continue

        import os
        from lib.paths import ENV_OVERRIDES

        env_name = ENV_OVERRIDES.get(key)
        if env_name and os.environ.get(env_name):
            source = f"env: {env_name}"
            color = Color.BRIGHT_MAGENTA
        elif context["config"].get(f"paths.{key}"):
            source = "config.yml"
            color = Color.BRIGHT_CYAN
        else:
            source = "default"
            color = Color.BRIGHT_BLACK

        exists = Path(value).exists() if key != "email_out_dir" else True
        mark = (
            console.colored("✔", Color.BRIGHT_GREEN)
            if exists
            else console.colored("·", Color.BRIGHT_BLACK)
        )

        rows.append([
            #mark,
            key,
            value,
            console.colored(source, color),
        ])

    console.table(
        headers=[
            #"",
            "Key",
            "Path",
            "Source"],
        rows=rows,
        align=["c", "l", "l", "l"]
    )

    console.newline()
    console.key_value("Config file", str(paths.config_path))
    return 0
