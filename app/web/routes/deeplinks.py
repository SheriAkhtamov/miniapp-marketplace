from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.core import get_db
from app.database.models import Category, Product
from app.utils.deeplinks import parse_start_param

router = APIRouter(tags=["deeplinks"])


@router.get("/admin/share-link-config")
async def admin_share_link_config():
    return {
        "bot_username": settings.BOT_USERNAME.strip().lstrip("@"),
        "mini_app_short_name": settings.TELEGRAM_MINI_APP_SHORT_NAME.strip().strip("/"),
        "web_base_url": settings.WEB_BASE_URL.rstrip("/"),
    }


@router.get("/shop/deeplink/{payload}")
async def shop_deep_link(payload: str, session: AsyncSession = Depends(get_db)):
    target = parse_start_param(payload)
    if not target:
        return RedirectResponse("/shop", status_code=303)

    target_type, target_id = target
    if target_type == "category":
        return RedirectResponse(f"/shop/category/{target_id}?from_startapp=1", status_code=303)

    product = (
        await session.execute(
            select(Product)
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.id == target_id,
                Product.is_active == True,
                Category.is_active == True,
            )
        )
    ).scalar_one_or_none()
    if not product:
        return RedirectResponse("/shop?from_startapp=1", status_code=303)

    return RedirectResponse(
        f"/shop/category/{product.category_id}?product_id={product.id}&from_startapp=1",
        status_code=303,
    )
