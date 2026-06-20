#!/usr/bin/env sh
set -eu

project_name="shotsight2-smoke"

if docker compose version >/dev/null 2>&1; then
    compose() {
        docker compose "$@"
    }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() {
        docker-compose "$@"
    }
else
    echo "Docker Compose is required (plugin or docker-compose command)." >&2
    exit 1
fi

cleanup() {
    compose --project-name "$project_name" down --volumes --remove-orphans
}

trap cleanup EXIT INT TERM

compose version
compose --project-name "$project_name" config --quiet
compose --project-name "$project_name" build
compose --project-name "$project_name" up --detach --wait --wait-timeout 120

python3 -c "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:4173/health', timeout=5); payload = json.load(response); assert response.status == 200 and payload['status'] == 'ok'; print(json.dumps(payload, sort_keys=True))"
compose --project-name "$project_name" ps
