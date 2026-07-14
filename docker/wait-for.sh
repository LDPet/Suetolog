#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: wait-for.sh HOST PORT" >&2
    exit 2
fi

host="$1"
port="$2"
timeout="${WAIT_FOR_TIMEOUT_SECONDS:-60}"
elapsed=0

echo "Waiting for ${host}:${port} (timeout: ${timeout}s)..."
until python -c 'import socket, sys; connection = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=2); connection.close()' "$host" "$port" 2>/dev/null; do
    if [ "$elapsed" -ge "$timeout" ]; then
        echo "Timed out waiting for ${host}:${port}" >&2
        exit 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done
echo "${host}:${port} is available"
