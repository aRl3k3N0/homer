#!/usr/bin/env bash
# publish.sh — публикация в PyPI.
#
# Переменные:
#   TWINE_REPOSITORY=pypi|testpypi
#   TWINE_USERNAME=__token__
#   TWINE_PASSWORD=<token>

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"
"$py" -m pip install --quiet twine

section "twine upload"
"$py" -m twine upload dist/* --non-interactive
ok "Публикация завершена"
