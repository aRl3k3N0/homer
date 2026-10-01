#!/usr/bin/env bash
# benchmark.sh — pytest-benchmark.
#
# Переменные:
#   COMPARE=main       — сравнить с сохранённым прогоном ветки main
#   SAVE=1             — сохранить результат в .benchmarks/
#   JSON=benchmark.json — путь для JSON-вывода

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"
COMPARE="${COMPARE:-}"
SAVE="${SAVE:-1}"
JSON="${JSON:-benchmark.json}"

mkdir -p .benchmarks

BENCH_ARGS=(
    benchmarks/
    --benchmark-only
    "--benchmark-json=$JSON"
    --benchmark-columns=min,max,mean,stddev,median,ops
)

[ "$SAVE" = "1" ] && BENCH_ARGS+=(--benchmark-autosave --benchmark-storage=.benchmarks)
[ -n "$COMPARE" ] && BENCH_ARGS+=("--benchmark-compare=^$COMPARE")

section "Benchmark"
"$py" -m pytest "${BENCH_ARGS[@]}"
ok "Бенчмарки завершены, результат: $JSON"
