#!/usr/bin/env bash
# docker.sh — сборка и публикация Docker-образа.
#
# Переменные:
#   REGISTRY=ghcr.io           — реестр
#   IMAGE=homer                — имя образа (без тега)
#   IMAGE_OWNER=user           — владелец/namespace
#   TAG=                       — тег (если не задан, вычисляется автоматически)
#   PUSH=0|1                   — пушить ли (по умолчанию 0)
#   PLATFORMS=linux/amd64,linux/arm64
#   LOGIN=1                    — сделать login (по умолчанию 0)
#   REGISTRY_USER=, REGISTRY_TOKEN=

source "$(dirname "$0")/_lib.sh"

cd "$(project_root)"

REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE="${IMAGE:-homer}"
IMAGE_OWNER="${IMAGE_OWNER:-}"
PUSH="${PUSH:-0}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
LOGIN="${LOGIN:-0}"

if ! have docker; then
    err "docker не установлен"
    exit 127
fi

# ─────────── Вычисление тегов ───────────
compute_tags() {
    local ref
    if [ -n "${TAG:-}" ]; then
        ref="$TAG"
    elif [ -n "${CI_COMMIT_TAG:-}" ]; then
        ref="$CI_COMMIT_TAG"           # GitLab
    elif [ -n "${GITHUB_REF_NAME:-}" ] && [[ "$GITHUB_REF_NAME" == v* ]]; then
        ref="$GITHUB_REF_NAME"         # GitHub
    else
        ref="${GITHUB_REF_NAME:-${CI_COMMIT_REF_SLUG:-edge}}"
    fi

    local full="${REGISTRY}"
    [ -n "$IMAGE_OWNER" ] && full="$full/$IMAGE_OWNER"
    full="$full/$IMAGE"

    local tags=()
    if [[ "$ref" == v*.*.* ]]; then
        local v="${ref#v}"
        local major minor
        major="${v%%.*}"
        minor="${v%.*}"
        tags+=("$full:$v" "$full:$minor" "$full:$major" "$full:latest")
    else
        tags+=("$full:$ref" "$full:sha-${CI_COMMIT_SHORT_SHA:-${GITHUB_SHA:0:7}}")
    fi
    printf '%s\n' "${tags[@]}"
}

mapfile -t TAGS < <(compute_tags)

section "Docker build"
hint "Реестр: $REGISTRY"
hint "Образ: $IMAGE"
hint "Теги: ${TAGS[*]}"
hint "Платформы: $PLATFORMS"
hint "Push: $PUSH"

# ─────────── Login (если просили) ───────────
if [ "$LOGIN" = "1" ]; then
    section "Docker login $REGISTRY"
    echo "${REGISTRY_TOKEN:-}" | docker login "$REGISTRY" \
        -u "${REGISTRY_USER:-}" --password-stdin
fi

# ─────────── Buildx ───────────
if ! docker buildx inspect homer-builder >/dev/null 2>&1; then
    docker buildx create --name homer-builder --use >/dev/null
fi
docker buildx use homer-builder >/dev/null

TAG_ARGS=()
for t in "${TAGS[@]}"; do
    TAG_ARGS+=(-t "$t")
done

docker buildx build \
    --platform "$PLATFORMS" \
    --push="$PUSH" \
    --cache-from type=gha \
    --cache-to type=gha,mode=max \
    --provenance=true \
    --sbom=true \
    "${TAG_ARGS[@]}" \
    .

ok "Docker-образ собран${PUSH:+, запушен}"
