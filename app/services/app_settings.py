from datetime import datetime
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AppSetting

SHOP_ALL_PRODUCTS_IMAGE_KEY = "shop_all_products_image_path"
PICKUP_ENABLED_KEY = "pickup_enabled"
PICKUP_ADDRESS_KEY = "pickup_address"
DELIVERY_OPTIONS_KEY = "delivery_options"
CARD_TRANSFER_NUMBER_KEY = "card_transfer_card_number"
CARD_TRANSFER_HOLDER_KEY = "card_transfer_card_holder"

DEFAULT_PICKUP_ADDRESS = "г. Ташкент, Чиланзарский район, 1-квартал, дом 1."
DEFAULT_CARD_TRANSFER_NUMBER = ""
DEFAULT_CARD_TRANSFER_HOLDER = ""
DEFAULT_DELIVERY_OPTIONS = [
    {
        "id": "express",
        "name_ru": "Экспресс-доставка",
        "name_uz": "Ekspress yetkazib berish",
        "price": 60000,
        "is_active": True,
    },
    {
        "id": "tomorrow",
        "name_ru": "Доставка на завтра",
        "name_uz": "Ertangi kunga yetkazib berish",
        "price": 40000,
        "is_active": True,
    },
    {
        "id": "cargo",
        "name_ru": "Грузовая доставка",
        "name_uz": "Yuk yetkazib berish",
        "price": 50000,
        "is_active": True,
    },
]


async def get_app_setting(session: AsyncSession, key: str) -> Optional[str]:
    setting = await session.get(AppSetting, key)
    if not setting or not setting.value:
        return None
    return setting.value


async def set_app_setting(session: AsyncSession, key: str, value: Optional[str]) -> None:
    setting = await session.get(AppSetting, key)
    if setting:
        setting.value = value or None
        setting.updated_at = datetime.utcnow()
        return

    session.add(AppSetting(key=key, value=value or None))


async def get_shop_all_products_image(session: AsyncSession) -> Optional[str]:
    return await get_app_setting(session, SHOP_ALL_PRODUCTS_IMAGE_KEY)


async def set_shop_all_products_image(session: AsyncSession, value: Optional[str]) -> None:
    await set_app_setting(session, SHOP_ALL_PRODUCTS_IMAGE_KEY, value)


def _normalize_delivery_option(raw: dict, index: int = 0) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    option_id = str(raw.get("id") or f"delivery_{index + 1}").strip()
    name_ru = str(raw.get("name_ru") or "").strip()
    name_uz = str(raw.get("name_uz") or "").strip()
    if not option_id or not name_ru:
        return None
    if not name_uz:
        name_uz = name_ru

    try:
        price = int(raw.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    price = max(0, price)

    return {
        "id": option_id,
        "name_ru": name_ru,
        "name_uz": name_uz,
        "price": price,
        "is_active": bool(raw.get("is_active", True)),
    }


def normalize_delivery_options(raw_options) -> list[dict]:
    if not isinstance(raw_options, list):
        return [option.copy() for option in DEFAULT_DELIVERY_OPTIONS]

    options = []
    seen_ids = set()
    for idx, raw in enumerate(raw_options):
        option = _normalize_delivery_option(raw, idx)
        if not option or option["id"] in seen_ids:
            continue
        seen_ids.add(option["id"])
        options.append(option)

    return options or [option.copy() for option in DEFAULT_DELIVERY_OPTIONS]


async def get_pickup_enabled(session: AsyncSession) -> bool:
    value = await get_app_setting(session, PICKUP_ENABLED_KEY)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


async def set_pickup_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_app_setting(session, PICKUP_ENABLED_KEY, "1" if enabled else "0")


async def get_pickup_address(session: AsyncSession) -> str:
    return (await get_app_setting(session, PICKUP_ADDRESS_KEY)) or DEFAULT_PICKUP_ADDRESS


async def set_pickup_address(session: AsyncSession, value: Optional[str]) -> None:
    await set_app_setting(session, PICKUP_ADDRESS_KEY, (value or "").strip() or DEFAULT_PICKUP_ADDRESS)


async def get_card_transfer_details(session: AsyncSession) -> dict:
    return {
        "card_number": (await get_app_setting(session, CARD_TRANSFER_NUMBER_KEY)) or DEFAULT_CARD_TRANSFER_NUMBER,
        "card_holder": (await get_app_setting(session, CARD_TRANSFER_HOLDER_KEY)) or DEFAULT_CARD_TRANSFER_HOLDER,
    }


async def set_card_transfer_details(
    session: AsyncSession,
    *,
    card_number: Optional[str],
    card_holder: Optional[str],
) -> None:
    await set_app_setting(session, CARD_TRANSFER_NUMBER_KEY, (card_number or "").strip())
    await set_app_setting(session, CARD_TRANSFER_HOLDER_KEY, (card_holder or "").strip())


async def get_delivery_options(session: AsyncSession, *, active_only: bool = False) -> list[dict]:
    raw = await get_app_setting(session, DELIVERY_OPTIONS_KEY)
    try:
        parsed = json.loads(raw) if raw else DEFAULT_DELIVERY_OPTIONS
    except (TypeError, ValueError):
        parsed = DEFAULT_DELIVERY_OPTIONS

    options = normalize_delivery_options(parsed)
    if active_only:
        active_options = [option for option in options if option.get("is_active")]
        return active_options or [option.copy() for option in DEFAULT_DELIVERY_OPTIONS]
    return options


async def set_delivery_options(session: AsyncSession, options: list[dict]) -> None:
    normalized = normalize_delivery_options(options)
    await set_app_setting(
        session,
        DELIVERY_OPTIONS_KEY,
        json.dumps(normalized, ensure_ascii=False),
    )


def find_delivery_option(options: list[dict], option_id: Optional[str]) -> Optional[dict]:
    if not options:
        return None
    if option_id:
        for option in options:
            if option["id"] == option_id:
                return option
    return options[0]


def get_min_order_quantity_for_product(product) -> int:
    """Return the smallest purchasable quantity in the product's sale unit.

    A product sold by the piece can be bought one at a time.  A product sold
    by the pack can be bought one pack at a time; ``pack_quantity`` describes
    the contents of that pack and must not impose an additional 100-item
    minimum.
    """
    return 1
