#!/usr/bin/env bash
# test.sh — pytest.
#
# Переменные:
#   FAST=1         — без покрытия, без matrix (одна версия Python)
#   COVERAGE=1     — с покрытием (по умолчанию 0)
#   COV_MIN=40     — минимальный % покрытия
#   MARKERS=""     — фильтр по маркерам (например, "not integration")
#   TESTS=""       — путь к тестам (по умолчанию tests/)
#   EXTRA_ARGS=""  — дополнительные аргументы pytest

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"
TESTS="${TESTS:-tests}"
MARKERS="${MARKERS:-}"
COVERAGE="${COVERAGE:-0}"
COV_MIN="${COV_MIN:-40}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

PYTEST_ARGS=("$TESTS" -q --maxfail=1 --timeout=60)

if [ -n "$MARKERS" ]; then
    PYTEST_ARGS+=(-m "$MARKERS")
fi

if [ "$COVERAGE" = "1" ]; then
    PYTEST_ARGS+=(
        --cov=lib
        --cov-report=term-missing
        --cov-report=xml:coverage.xml
        --cov-report=html:htmlcov
        "--cov-fail-under=$COV_MIN"
    )
fi

# shellcheck disable=SC2206
[ -n "$EXTRA_ARGS" ] && PYTEST_ARGS+=($EXTRA_ARGS)

section "pytest"
"$py" -m pytest "${PYTEST_ARGS[@]}"

if [ "$COVERAGE" = "1" ] && [ -f coverage.xml ]; then
    ok "Покрытие записано в coverage.xml и htmlcov/"
fi

ok "Тесты прошли"
