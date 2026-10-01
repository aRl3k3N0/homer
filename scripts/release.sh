#!/usr/bin/env bash
# release.sh — python-semantic-release.
#
# Переменные:
#   DRY=1        — только показать, что будет сделано
#   NO_PUSH=1    — не пушить (для локальной проверки)
#   GH_TOKEN=    — токен (для GitHub/SourceCraft)
#   GITLAB_TOKEN= — для GitLab

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"
ensure_deps dev

py="$(detect_python)"

if ! "$py" -m semantic_release --version >/dev/null 2>&1; then
    "$py" -m pip install "python-semantic-release>=9.0"
fi

git config user.name  "homer-ci" 2>/dev/null || true
git config user.email "homer-ci@example.com" 2>/dev/null || true

if [ "${DRY:-0}" = "1" ]; then
    section "Semantic Release (dry-run)"
    "$py" -m semantic_release version --print
    ok "Dry-run завершён"
    exit 0
fi

section "Semantic Release: version"
"$py" -m semantic_release version

if [ "${NO_PUSH:-0}" = "1" ]; then
    warn "NO_PUSH=1 — тег и commit созданы, но не запушены"
    exit 0
fi

section "Semantic Release: publish"
"$py" -m semantic_release publish
ok "Релиз опубликован"
