#!/usr/bin/env bash
# notify.sh — уведомление о результате CI.
#
# Переменные:
#   PROVIDER=mattermost|slack|telegram|none
#   STATUS=success|failed|canceled
#   JOB_NAME=, BUILD_URL=, BRANCH=, COMMIT=
#   WEBHOOK_URL= (для mattermost/slack)
#   TELEGRAM_TOKEN=, TELEGRAM_CHAT= (для telegram)

source "$(dirname "$0")/_lib.sh"

PROVIDER="${PROVIDER:-none}"
STATUS="${STATUS:-success}"
JOB_NAME="${JOB_NAME:-CI}"
BUILD_URL="${BUILD_URL:-}"
BRANCH="${BRANCH:-}"
COMMIT="${COMMIT:-}"

[ "$PROVIDER" = "none" ] && exit 0

icon="✅"
[ "$STATUS" = "failed" ] && icon="❌"
[ "$STATUS" = "canceled" ] && icon="⚠️"

text="$icon *$JOB_NAME* — $STATUS
Ветка: \`$BRANCH\`
Коммит: \`$COMMIT\`
${BUILD_URL:+Сборка: $BUILD_URL}"

case "$PROVIDER" in
    mattermost)
        [ -z "${WEBHOOK_URL:-}" ] && { warn "WEBHOOK_URL не задан"; exit 0; }
        payload=$(cat <<EOF
{"text":"$text","username":"Homer CI"}
EOF
)
        curl -fsS -X POST -H 'Content-Type: application/json' \
             -d "$payload" "$WEBHOOK_URL" >/dev/null
        ;;
    slack)
        [ -z "${WEBHOOK_URL:-}" ] && { warn "WEBHOOK_URL не задан"; exit 0; }
        curl -fsS -X POST -H 'Content-Type: application/json' \
             -d "{\"text\":\"$text\"}" "$WEBHOOK_URL" >/dev/null
        ;;
    telegram)
        [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT:-}" ] && {
            warn "TELEGRAM_TOKEN или TELEGRAM_CHAT не задан"; exit 0;
        }
        curl -fsS -X POST \
             "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
             -d "chat_id=$TELEGRAM_CHAT&parse_mode=Markdown&text=$text" \
             >/dev/null
        ;;
    *) warn "Неизвестный PROVIDER: $PROVIDER" ;;
esac

ok "Уведомление отправлено ($PROVIDER)"
