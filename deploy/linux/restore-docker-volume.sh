#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    printf 'Usage: %s BACKUP_ARCHIVE NEW_VOLUME_NAME\n' "$0" >&2
    exit 2
fi

archive="$1"
volume_name="$2"
image_name="${IMAGE_NAME:-hk-us-quant-system:${IMAGE_TAG:-latest}}"

if [[ ! -f "${archive}" ]]; then
    printf 'Backup archive not found: %s\n' "${archive}" >&2
    exit 2
fi
if [[ ! "${volume_name}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]]; then
    printf 'Invalid Docker volume name: %s\n' "${volume_name}" >&2
    exit 2
fi
if docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    printf 'Refusing to overwrite existing Docker volume: %s\n' "${volume_name}" >&2
    exit 2
fi
if ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    printf 'Docker image not found: %s (run docker compose build first)\n' "${image_name}" >&2
    exit 2
fi

tar -tzf "${archive}" >/dev/null
docker volume create "${volume_name}" >/dev/null

restore_ok=0
cleanup() {
    if [[ "${restore_ok}" != "1" ]]; then
        docker volume rm "${volume_name}" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

docker run --rm --user 0:0 -i \
    -v "${volume_name}:/restore" \
    "${image_name}" \
    sh -c 'tar -C /restore -xzf - && chown -R 10001:10001 /restore' <"${archive}"

restore_ok=1
trap - EXIT
printf 'Restored into new volume: %s\n' "${volume_name}"
printf 'Set DATA_VOLUME_NAME=%s in .env, then run docker compose up -d.\n' "${volume_name}"
