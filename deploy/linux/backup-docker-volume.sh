#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/compose.yaml}"
BACKUP_DIR="${1:-/var/backups/hk-us-quant}"

mkdir -p -- "${BACKUP_DIR}"
BACKUP_DIR="$(cd -- "${BACKUP_DIR}" && pwd -P)"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="${BACKUP_DIR}/hk-us-quant-data-${timestamp}.tar.gz"
temporary="${archive}.partial"
was_running=0

cleanup() {
    rm -f -- "${temporary}"
    if [[ "${was_running}" == "1" ]]; then
        docker compose -f "${COMPOSE_FILE}" start quant-app >/dev/null
    fi
}
trap cleanup EXIT

if docker compose -f "${COMPOSE_FILE}" ps --status running --services | grep -Fxq quant-app; then
    was_running=1
    docker compose -f "${COMPOSE_FILE}" stop quant-app >/dev/null
fi

docker compose -f "${COMPOSE_FILE}" run --rm --no-deps -T quant-app \
    tar -C /app/backend/data -czf - . >"${temporary}"

tar -tzf "${temporary}" >/dev/null
mv -- "${temporary}" "${archive}"

if [[ "${was_running}" == "1" ]]; then
    docker compose -f "${COMPOSE_FILE}" start quant-app >/dev/null
    was_running=0
fi

trap - EXIT
printf '%s\n' "${archive}"
