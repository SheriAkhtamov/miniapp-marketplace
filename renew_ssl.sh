#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo ".env is missing. Cannot issue or renew certificates." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

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

mkdir -p certbot/www letsencrypt letsencrypt-lib final_certs logs

email_args=()
if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then
  email_args=(--email "$LETSENCRYPT_EMAIL")
else
  email_args=(--register-unsafely-without-email)
fi

domain_args=(-d "$DOMAIN")
if [ -n "${WWW_DOMAIN:-}" ]; then
  domain_args+=(-d "$WWW_DOMAIN")
fi

staging_args=()
if [ "${LETSENCRYPT_STAGING:-false}" = "true" ]; then
  staging_args=(--staging)
fi

docker run --rm \
  -v "$ROOT_DIR/certbot/www:/var/www/certbot" \
  -v "$ROOT_DIR/letsencrypt:/etc/letsencrypt" \
  -v "$ROOT_DIR/letsencrypt-lib:/var/lib/letsencrypt" \
  certbot/certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --agree-tos --non-interactive --keep-until-expiring \
  "${email_args[@]}" \
  "${staging_args[@]}" \
  "${domain_args[@]}"

cp -L "letsencrypt/live/$DOMAIN/fullchain.pem" final_certs/fullchain.pem
cp -L "letsencrypt/live/$DOMAIN/privkey.pem" final_certs/privkey.pem
chmod 644 final_certs/fullchain.pem
chmod 600 final_certs/privkey.pem

docker kill -s HUP shop_nginx >/dev/null 2>&1 || true
echo "TLS certificate is ready for $DOMAIN."
