#!/usr/bin/env bash
#
# Lanza la captura contra la API desplegada. Pensado para un Cron Job de Render
# o para cualquier cron externo.
#
# Variables:
#   ANTIFASIS_API_URL   URL completa (opcional; tiene prioridad).
#   ANTIFASIS_API_HOST  Host de Render, por ejemplo antifasis-api.onrender.com.
#   ANTIFASIS_API_TOKEN Token compartido con el servicio web.
#
set -euo pipefail

: "${ANTIFASIS_API_TOKEN:?Define ANTIFASIS_API_TOKEN}"

if [[ -n "${ANTIFASIS_API_URL:-}" ]]; then
    URL="${ANTIFASIS_API_URL%/}"
else
    : "${ANTIFASIS_API_HOST:?Define ANTIFASIS_API_HOST o ANTIFASIS_API_URL}"
    HOST="${ANTIFASIS_API_HOST%/}"
    case "$HOST" in
        http://*|https://*) URL="$HOST" ;;
        *) URL="https://$HOST" ;;
    esac
fi

curl --fail --silent --show-error \
    --max-time 240 \
    --retry 3 --retry-delay 10 --retry-connrefused \
    -X POST "$URL/actualizar" \
    -H "Authorization: Bearer $ANTIFASIS_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data '{}'
printf '\n'
