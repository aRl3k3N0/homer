#!/usr/bin/env bash
# package.sh — сборка wheel + sdist.

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"

section "python -m build"
"$py" -m pip install --quiet build
rm -rf dist/
"$py" -m build
ls -la dist/
ok "Пакеты собраны в dist/"
