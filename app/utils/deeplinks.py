import re
from urllib.parse import quote

from app.config import settings


_START_PARAM_RE = re.compile(r"^(product|category)_(\d+)$")
PHONE_REGISTRATION_START_PARAM = "request_phone"


def _bot_username() -> str:
    return settings.BOT_USERNAME.strip().lstrip("@")


def build_telegram_start_link(payload: str) -> str:
    safe_payload = quote(payload, safe="-_")
    bot_username = _bot_username()
    app_short_name = settings.TELEGRAM_MINI_APP_SHORT_NAME.strip().strip("/")

    if bot_username and app_short_name:
        return f"https://t.me/{bot_username}/{app_short_name}?startapp={safe_payload}"
    if bot_username:
        return f"https://t.me/{bot_username}?startapp={safe_payload}"

    base_url = settings.WEB_BASE_URL.rstrip("/")
    return f"{base_url}/shop?tgWebAppStartParam={safe_payload}"


def phone_registration_start_link() -> str:
    """Return a Telegram bot link that starts the phone-sharing flow.

    This is intentionally a regular bot ``start`` link (not a Mini App
    ``startapp`` link), so Telegram returns the customer to the bot chat where
    the contact-request keyboard can be displayed.
    """
    bot_username = _bot_username()
    if not bot_username:
        return ""
    return f"https://t.me/{bot_username}?start={PHONE_REGISTRATION_START_PARAM}"


def product_start_link(product_id: int) -> str:
    return build_telegram_start_link(f"product_{int(product_id)}")


def category_start_link(category_id: int) -> str:
    return build_telegram_start_link(f"category_{int(category_id)}")


def parse_start_param(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None

    match = _START_PARAM_RE.fullmatch(value.strip())
    if not match:
        return None

    return match.group(1), int(match.group(2))
