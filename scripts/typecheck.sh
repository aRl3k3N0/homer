#!/usr/bin/env bash
# typecheck.sh — mypy.
#
# Переменные:
#   TARGET=lib|tests|all    — что проверять (по умолчанию lib)
#   STRICT=1                — использовать strict-профиль

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"
TARGET="${TARGET:-lib}"

MYPY_ARGS=(--config-file=mypy.ini)
[ "${STRICT:-0}" = "1" ] && MYPY_ARGS+=(--strict)

case "$TARGET" in
    lib)   MYPY_ARGS+=(lib) ;;
    tests) MYPY_ARGS+=(tests) ;;
    all)   MYPY_ARGS+=(lib tests) ;;
    *)     err "TARGET должен быть lib|tests|all"; exit 2 ;;
esac

section "mypy ($TARGET)"
"$py" -m mypy "${MYPY_ARGS[@]}"
ok "Типизация прошла"
