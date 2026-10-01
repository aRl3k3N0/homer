#!/usr/bin/env bash
# bootstrap.sh — установка зависимостей.
#
# Использование:
#   ./scripts/bootstrap.sh           # dev-зависимости
#   MODE=prod ./scripts/bootstrap.sh # только prod
#   MODE=docs ./scripts/bootstrap.sh # + Sphinx

source "$(dirname "$0")/_lib.sh"

MODE="${MODE:-dev}"

case "$MODE" in
    prod|dev|docs) ;;
    *) err "MODE должен быть prod|dev|docs"; exit 2 ;;
esac

ensure_deps "$MODE"

if [ "$MODE" = "docs" ]; then
    section "Документация: доп. зависимости"
    py="$(detect_python)"
    "$py" -m pip install Sphinx sphinx-rtd-theme myst-parser
fi

ok "Bootstrap завершён (режим: $MODE)"
