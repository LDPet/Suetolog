#!/usr/bin/env sh
set -eu

if [ -n "${POSTGRES_HOST:-}" ]; then
    /app/docker/wait-for.sh "$POSTGRES_HOST" "${POSTGRES_PORT:-5432}"
fi

if [ "${WAIT_FOR_REDIS:-1}" = "1" ]; then
    /app/docker/wait-for.sh "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}"
fi

exec "$@"
