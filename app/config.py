import json
import os

from dotenv import load_dotenv


load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value!r}")


def _env_int_list(name: str, default: list[int] | None = None) -> list[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default or []

    value = value.strip()
    if value.startswith("["):
        parsed = json.loads(value)
        return [int(item) for item in parsed]

    return [int(item.strip()) for item in value.split(",") if item.strip()]


class Settings:
    # --- Bot ---
    SECRET_KEY = _env_str("SECRET_KEY")
    BOT_TOKEN = _env_str("BOT_TOKEN")
    BOT_USERNAME = _env_str("BOT_USERNAME")
    TELEGRAM_MINI_APP_SHORT_NAME = _env_str("TELEGRAM_MINI_APP_SHORT_NAME")
    ADMIN_IDS = _env_int_list("ADMIN_IDS", [7719402429])

    # --- Superadmin ---
    SUPERADMIN_LOGIN = _env_str("SUPERADMIN_LOGIN", "UnicoM")
    SUPERADMIN_PASSWORD = _env_str("SUPERADMIN_PASSWORD")
    SYNC_SUPERADMIN_PASSWORD = _env_bool("SYNC_SUPERADMIN_PASSWORD", True)

    # --- Database ---
    DB_USER = _env_str("DB_USER", "postgres")
    DB_PASS = _env_str("DB_PASS", "postgres")
    DB_HOST = _env_str("DB_HOST", "db")
    DB_PORT = _env_int("DB_PORT", 5432)
    DB_NAME = _env_str("DB_NAME", "shop_db")
    DATABASE_URL_OVERRIDE = _env_str("DATABASE_URL")

    # --- Site ---
    WEB_BASE_URL = _env_str("WEB_BASE_URL", "https://unicombot.uz")
    HR_WORKSPACE_URL = _env_str("HR_WORKSPACE_URL", "/hr/")
    HR_INTERNAL_URL = _env_str("HR_INTERNAL_URL", "http://hr:3000")
    SESSION_HTTPS_ONLY = _env_bool("SESSION_HTTPS_ONLY", True)

    # --- Payme ---
    PAYME_ID = _env_str("PAYME_ID")
    PAYME_KEY = _env_str("PAYME_KEY")
    PAYME_URL = _env_str("PAYME_URL", "https://checkout.paycom.uz")
    PAYME_ACCOUNT_FIELD = _env_str("PAYME_ACCOUNT_FIELD", "order_id")
    PAYME_MIN_AMOUNT = _env_int("PAYME_MIN_AMOUNT", 100000)

    # --- Click ---
    CLICK_SERVICE_ID = _env_str("CLICK_SERVICE_ID")
    CLICK_MERCHANT_ID = _env_str("CLICK_MERCHANT_ID")
    CLICK_SECRET_KEY = _env_str("CLICK_SECRET_KEY")
    CLICK_MERCHANT_USER_ID = _env_str("CLICK_MERCHANT_USER_ID")

    ORDER_PAYMENT_TIMEOUT_MINUTES = _env_int("ORDER_PAYMENT_TIMEOUT_MINUTES", 20)
    MIN_ORDER_AMOUNT = _env_int("MIN_ORDER_AMOUNT", 100)
    DEFAULT_PACKAGE_CODE = _env_str("DEFAULT_PACKAGE_CODE", "000000")

    # --- Redis ---
    REDIS_URL = _env_str("REDIS_URL", "redis://redis:6379/0")
    CACHE_TTL = _env_int("CACHE_TTL", 300)

    # --- Rate limiting ---
    RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 60)
    LOGIN_RATE_LIMIT = _env_str("LOGIN_RATE_LIMIT", "5/minute")

    # --- Admin notifications ---
    NOTIFY_ADMINS_ON_NEW_ORDER = _env_bool("NOTIFY_ADMINS_ON_NEW_ORDER", True)

    @property
    def DATABASE_URL(self):
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
