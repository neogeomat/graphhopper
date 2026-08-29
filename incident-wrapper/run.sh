#!/usr/bin/env bash
# Bootstraps a local venv (first run) and starts the incident/custom-model wrapper.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

# Local secrets/config (gitignored): BAATO_KEY, GRAPHOPPER_URL, INCIDENTS_DB, PORT
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# Keep one incident DB for both host and Docker runs: docker-compose mounts
# ./data at /data, so the container writes the very same file.
mkdir -p data
export INCIDENTS_DB="${INCIDENTS_DB:-$PWD/data/incidents.db}"

exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
