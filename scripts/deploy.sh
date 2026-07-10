#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env is missing. Provide it before deployment." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is not installed. Run scripts/install_docker.sh first." >&2
  exit 1
fi

DOMAIN="${DOMAIN:-}"
if [ -z "$DOMAIN" ] && [ -n "${WEB_BASE_URL:-}" ]; then
  DOMAIN="$(python3 - <<'PY'
import os
from urllib.parse import urlparse
print(urlparse(os.environ["WEB_BASE_URL"]).hostname or "")
PY
)"
fi

if [ -z "$DOMAIN" ]; then
  echo "DOMAIN or WEB_BASE_URL must be set in .env." >&2
  exit 1
fi

mkdir -p backups/rollback logs media final_certs certbot/www letsencrypt letsencrypt-lib nginx
python3 scripts/render_nginx_conf.py

if [ ! -s final_certs/fullchain.pem ] || [ ! -s final_certs/privkey.pem ]; then
  echo "Creating temporary self-signed certificate for first nginx start..."
  if command -v openssl >/dev/null 2>&1; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 2 \
      -subj "/CN=${DOMAIN}" \
      -keyout final_certs/privkey.pem \
      -out final_certs/fullchain.pem >/dev/null 2>&1
  else
    docker run --rm -v "$PWD/final_certs:/certs" alpine/openssl req -x509 -nodes -newkey rsa:2048 -days 2 \
      -subj "/CN=${DOMAIN}" \
      -keyout /certs/privkey.pem \
      -out /certs/fullchain.pem >/dev/null 2>&1
  fi
  chmod 644 final_certs/fullchain.pem
  chmod 600 final_certs/privkey.pem
fi

"${COMPOSE[@]}" config >/dev/null
echo "Building HR workspace assets..."
"${COMPOSE[@]}" run --rm --no-deps hr sh -c "npm ci && VITE_BASE_PATH=/hr/ npm run build"
"${COMPOSE[@]}" up -d --build --remove-orphans

if [ "${ENABLE_LETSENCRYPT:-true}" != "false" ]; then
  ./renew_ssl.sh
fi

HEALTHCHECK_URL="${DEPLOY_HEALTHCHECK_URL:-https://${DOMAIN}/health}"
echo "Checking ${HEALTHCHECK_URL}..."

if command -v curl >/dev/null 2>&1; then
  curl --fail --silent --show-error --retry 12 --retry-delay 5 "$HEALTHCHECK_URL" >/dev/null
else
  docker run --rm curlimages/curl:latest --fail --silent --show-error --retry 12 --retry-delay 5 "$HEALTHCHECK_URL" >/dev/null
fi

HR_HEALTHCHECK_URL="${DEPLOY_HR_HEALTHCHECK_URL:-https://${DOMAIN}/hr/health}"
echo "Checking ${HR_HEALTHCHECK_URL}..."

if command -v curl >/dev/null 2>&1; then
  if ! curl --fail --silent --show-error --retry 12 --retry-delay 5 "$HR_HEALTHCHECK_URL" >/dev/null; then
    echo "HR healthcheck failed. Recent HR container logs:" >&2
    "${COMPOSE[@]}" logs --tail=120 hr >&2 || docker logs --tail=120 shop_hr >&2 || true
    exit 1
  fi
else
  if ! docker run --rm curlimages/curl:latest --fail --silent --show-error --retry 12 --retry-delay 5 "$HR_HEALTHCHECK_URL" >/dev/null; then
    echo "HR healthcheck failed. Recent HR container logs:" >&2
    "${COMPOSE[@]}" logs --tail=120 hr >&2 || docker logs --tail=120 shop_hr >&2 || true
    exit 1
  fi
fi

"${COMPOSE[@]}" ps
echo "Deployment finished."
