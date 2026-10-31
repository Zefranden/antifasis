#!/usr/bin/env bash
#
# Captura diaria para cron. Escribe la salida en logs/antifasis.log.
# Uso:
#   ./scripts/cron_diario.sh
#   PYTHON_BIN=/usr/bin/python3 ./scripts/cron_diario.sh
#
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

PYTHON_BIN="${PYTHON_BIN:-$RAIZ/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "No se encuentra el intérprete $PYTHON_BIN. Ejecuta primero: make install" >&2
    exit 1
fi

mkdir -p logs

{
    printf '\n=== %s ===\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
    "$PYTHON_BIN" -m antifasis actualizar "$@"
} >> logs/antifasis.log 2>&1
