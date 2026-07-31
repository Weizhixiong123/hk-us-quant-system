#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/compose.yaml}"

exec 9>/var/lock/hk-us-quant-update.lock
if ! flock -n 9; then
    printf 'Another image update is already running.\n' >&2
    exit 1
fi

cd -- "${PROJECT_DIR}"
if [[ ! -f .env ]]; then
    printf 'Missing %s/.env\n' "${PROJECT_DIR}" >&2
    exit 2
fi

expected_image="$(docker compose -f "${COMPOSE_FILE}" config --images | head -n 1)"
if [[ -z "${expected_image}" ]]; then
    printf 'Unable to resolve the Compose image name.\n' >&2
    exit 2
fi

current_container="$(docker compose -f "${COMPOSE_FILE}" ps -q quant-app)"
old_image_id=""
if [[ -n "${current_container}" ]]; then
    old_image_id="$(docker inspect --format '{{.Image}}' "${current_container}")"
fi

docker compose -f "${COMPOSE_FILE}" pull quant-app
new_image_id="$(docker image inspect --format '{{.Id}}' "${expected_image}")"

if [[ -n "${old_image_id}" && "${new_image_id}" == "${old_image_id}" ]]; then
    printf 'Already up to date: %s\n' "${expected_image}"
    exit 0
fi

if [[ -n "${current_container}" ]]; then
    bash "${SCRIPT_DIR}/backup-docker-volume.sh"
fi

wait_for_health() {
    local container_id="$1"
    local status=""
    for _ in $(seq 1 24); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
        case "${status}" in
            healthy|running)
                return 0
                ;;
            unhealthy|exited|dead)
                return 1
                ;;
        esac
        sleep 5
    done
    return 1
}

docker compose -f "${COMPOSE_FILE}" up -d --no-build --pull never quant-app
new_container="$(docker compose -f "${COMPOSE_FILE}" ps -q quant-app)"
if [[ -n "${new_container}" ]] && wait_for_health "${new_container}"; then
    printf 'Updated successfully: %s (%s)\n' "${expected_image}" "${new_image_id}"
    exit 0
fi

docker compose -f "${COMPOSE_FILE}" logs --tail=100 quant-app >&2 || true
if [[ -z "${old_image_id}" ]]; then
    printf 'Update failed and no previous image is available for rollback.\n' >&2
    exit 1
fi

printf 'Health check failed; rolling back to %s\n' "${old_image_id}" >&2
docker tag "${old_image_id}" "${expected_image}"
docker compose -f "${COMPOSE_FILE}" up -d --no-build --pull never --force-recreate quant-app
rollback_container="$(docker compose -f "${COMPOSE_FILE}" ps -q quant-app)"
if [[ -z "${rollback_container}" ]] || ! wait_for_health "${rollback_container}"; then
    printf 'Rollback also failed; manual intervention is required.\n' >&2
    exit 1
fi

printf 'Rollback succeeded. The failed update was not activated.\n' >&2
exit 1
