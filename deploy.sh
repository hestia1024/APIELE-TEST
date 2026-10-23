#!/usr/bin/env bash
set -euo pipefail
cd /opt/apiele-test
chmod 600 .env.server
mkdir -p logs

command -v docker >/dev/null || { echo 'Docker is required on this server.' >&2; exit 1; }
docker info >/dev/null

# Do not replace a different service occupying the requested web port.
if command -v ss >/dev/null && ss -H -ltn 'sport = :8010' | grep -q .; then
    if ! docker container inspect apiele-test-web >/dev/null 2>&1; then
        echo 'Port 8010 is already used by another service; deployment stopped.' >&2
        exit 1
    fi
fi

docker build -t apiele-test-web:latest .
if docker container inspect apiele-test-web >/dev/null 2>&1; then
    docker rm -f apiele-test-web >/dev/null
fi

# Host networking lets the app reach the existing MySQL mapping at 127.0.0.1:3307.
docker run -d --name apiele-test-web \
    --restart unless-stopped \
    --network host \
    --env-file .env.server \
    --mount "type=bind,src=$PWD/logs,dst=/app/logs" \
    --log-opt max-size=10m --log-opt max-file=3 \
    apiele-test-web:latest >/dev/null

docker exec -i apiele-test-web python - <<'PY'
import json
import time
import urllib.request

deadline = time.monotonic() + 25
while True:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=3) as response:
            if response.status == 200:
                break
    except OSError:
        if time.monotonic() >= deadline:
            raise SystemExit('App did not become ready. Run: docker logs --tail 60 apiele-test-web')
        time.sleep(1)

for label in ('initial', 'reused_connection'):
    start = time.perf_counter()
    with urllib.request.urlopen('http://127.0.0.1:8010/api/bootstrap', timeout=15) as response:
        data = json.load(response)
    print(json.dumps({'check': label, 'status': data['status'], 'ms': round((time.perf_counter()-start)*1000)}))
print('DEPLOYMENT_OK: web and MySQL are connected on the server.')
PY
