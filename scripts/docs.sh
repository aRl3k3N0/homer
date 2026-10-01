#!/usr/bin/env bash
# docs.sh — Sphinx.
#
# Переменные:
#   BUILD_DIR=docs/api-generated/_build/html  — куда собрать
#   STRICT=1                                  — warnings как errors (по умолчанию 1)
#   SERV=1                                    — поднять локальный сервер после сборки
#   PORT=8000                                 — порт сервера

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"
BUILD_DIR="${BUILD_DIR:-docs/api-generated/_build/html}"
STRICT="${STRICT:-1}"
SERV="${SERV:-0}"
PORT="${PORT:-8000}"

SPHINX_ARGS=(-b html docs/api-generated "$BUILD_DIR")
[ "$STRICT" = "1" ] && SPHINX_ARGS+=(-W --keep-going)

section "Sphinx build"
"$py" -m sphinx "${SPHINX_ARGS[@]}"
touch "$BUILD_DIR/.nojekyll"
ok "Документация: file://$(pwd)/$BUILD_DIR/index.html"

if [ "$SERV" = "1" ]; then
    section "Локальный сервер на http://localhost:$PORT"
    "$py" -m http.server "$PORT" --directory "$BUILD_DIR"
fi
