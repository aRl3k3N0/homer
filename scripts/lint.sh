#!/usr/bin/env bash
# lint.sh — ruff + flake8 + pre-commit.
#
# Переменные:
#   FAST=1    — пропустить pre-commit (быстрее)
#   STRICT=1  — warnings как errors
#   FIX=1     — автофиксы (ruff --fix)

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"

RUFF_ARGS=(check lib tests)
[ "${STRICT:-0}" = "1" ] && RUFF_ARGS+=(--no-fix)
[ "${FIX:-0}" = "1" ] && RUFF_ARGS+=(--fix)

section "Ruff"
"$py" -m ruff "${RUFF_ARGS[@]}"
ok "Ruff прошёл"

section "Flake8"
"$py" -m flake8 lib tests
ok "Flake8 прошёл"

if [ "$FAST" = "1" ]; then
    hint "FAST=1 — pre-commit пропущен"
else
    section "Pre-commit (по всем файлам)"
    if have pre-commit; then
        pre-commit run --all-files --show-diff-on-failure
        ok "Pre-commit прошёл"
    else
        hint "pre-commit не установлен — пропускаем"
    fi
fi

ok "Линтинг завершён"
