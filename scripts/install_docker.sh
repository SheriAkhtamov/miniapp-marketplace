#!/usr/bin/env bash
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  exit 0
fi

if command -v docker >/dev/null 2>&1 && command -v docker-compose >/dev/null 2>&1; then
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Docker is not installed, and this bootstrap installer supports apt-based Linux only." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release

if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends docker.io
fi

if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends docker-compose-v2 || \
  apt-get install -y --no-install-recommends docker-compose-plugin || \
  apt-get install -y --no-install-recommends docker-compose
fi

systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true

if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  echo "Docker installed, but Docker Compose is still unavailable." >&2
  exit 1
fi
