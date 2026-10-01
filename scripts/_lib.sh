#!/usr/bin/env bash
# Общие функции для всех скриптов Homer.
# Подключается через `source "$(dirname "$0")/_lib.sh"`.

set -euo pipefail

# ─────────── Цвета (если TTY и не отключены) ───────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'
    C_CYAN=$'\033[36m'
else
    C_RESET= C_BOLD= C_DIM= C_RED= C_GREEN= C_YELLOW= C_BLUE= C_CYAN=
fi

log()      { printf '%s\n' "${C_CYAN}▸${C_RESET} $*"; }
ok()       { printf '%s\n' "${C_GREEN}✔${C_RESET} $*"; }
warn()     { printf '%s\n' "${C_YELLOW}⚠${C_RESET} $*" >&2; }
err()      { printf '%s\n' "${C_RED}✖${C_RESET} $*" >&2; }
section()  { printf '\n%s\n' "${C_BOLD}${C_BLUE}═══ $* ═══${C_RESET}"; }
hint()     { printf '%s\n' "${C_DIM}$*${C_RESET}"; }

# ─────────── Определение Python-интерпретатора ───────────
# Приоритет: $PYTHON → .venv/bin/python → python3 → python
detect_python() {
    if [ -n "${PYTHON:-}" ]; then
        echo "$PYTHON"
        return
    fi
    local root
    root="$(project_root)"
    if [ -x "$root/.venv/bin/python" ]; then
        echo "$root/.venv/bin/python"
    elif [ -x "$root/.venv/Scripts/python.exe" ]; then
        echo "$root/.venv/Scripts/python.exe"   # Windows Git Bash / MSYS
    elif command -v python3 >/dev/null 2>&1; then
        echo python3
    elif command -v python >/dev/null 2>&1; then
        echo python
    else
        err "Python не найден"
        exit 127
    fi
}

# ─────────── Корень проекта ───────────
project_root() {
    if [ -n "${PROJECT_ROOT:-}" ]; then
        echo "$PROJECT_ROOT"
        return
    fi
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    echo "$dir"
}

# ─────────── Ленивая установка зависимостей ───────────
# Использование: ensure_deps dev|prod
ensure_deps() {
    local mode="${1:-dev}"
    local root
    root="$(project_root)"
    local marker="$root/.cache/homer/.deps-$mode"
    mkdir -p "$(dirname "$marker")"

    local req_files
    if [ "$mode" = "dev" ]; then
        req_files="$root/requirements.txt $root/requirements-dev.txt"
    else
        req_files="$root/requirements.txt"
    fi

    # Проверяем свежесть маркера (хеш файлов)
    local current_hash=""
    for f in $req_files; do
        [ -f "$f" ] || continue
        current_hash="$current_hash$(sha1sum "$f" 2>/dev/null | awk '{print $1}')"
    done

    if [ -f "$marker" ] && [ "$(cat "$marker")" = "$current_hash" ]; then
        hint "Зависимости ($mode) уже установлены"
        return
    fi

    section "Установка зависимостей ($mode)"
    local py
    py="$(detect_python)"
    "$py" -m pip install --upgrade pip
    for f in $req_files; do
        [ -f "$f" ] || continue
        log "pip install -r $(basename "$f")"
        "$py" -m pip install -r "$f"
    done
    echo "$current_hash" > "$marker"
    ok "Зависимости ($mode) установлены"
}

# ─────────── Проверка наличия команды ───────────
have() { command -v "$1" >/dev/null 2>&1; }

# ─────────── Определение ОС ───────────
is_windows() {
    case "${OSTYPE:-}" in
        msys*|cygwin*|win32) return 0 ;;
    esac
    [ "${OS:-}" = "Windows_NT" ]
}

is_macos() {
    [ "$(uname -s 2>/dev/null)" = "Darwin" ]
}

is_linux() {
    [ "$(uname -s 2>/dev/null)" = "Linux" ]
}

# ─────────── Параметры режимов ───────────
# Используется в test.sh, lint.sh и т. п.
# FAST=1 — быстрый режим (одна версия Python, без покрытия, без matrix)
# CI=1   — в CI (меняет вывод, отключает интерактив)
# STRICT=1 — предупреждения как ошибки
FAST="${FAST:-0}"
CI="${CI:-0}"
STRICT="${STRICT:-0}"
