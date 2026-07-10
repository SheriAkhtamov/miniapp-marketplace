#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TEMPLATE_PATH = ROOT / "nginx" / "shop_ssl.conf.template"
OUTPUT_PATH = ROOT / "nginx" / "shop_ssl.conf"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def domain_from_env() -> str:
    domain = os.getenv("DOMAIN", "").strip()
    if domain:
        return domain

    web_base_url = os.getenv("WEB_BASE_URL", "").strip()
    if web_base_url:
        parsed = urlparse(web_base_url)
        if parsed.hostname:
            return parsed.hostname

    raise SystemExit("DOMAIN or WEB_BASE_URL must be set in .env")


def main() -> None:
    load_env_file(ENV_PATH)

    domain = domain_from_env()
    www_domain = os.getenv("WWW_DOMAIN", "").strip()

    names = [domain]
    if www_domain:
        names.append(www_domain)

    server_names = " ".join(dict.fromkeys(names))
    rendered = TEMPLATE_PATH.read_text(encoding="utf-8").replace("__SERVER_NAMES__", server_names)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Rendered nginx config for: {server_names}")


if __name__ == "__main__":
    main()
