from typing import List
import asyncio
import re
import os
import uuid
import aiofiles
import aiohttp
from datetime import datetime, timedelta
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Depends, HTTPException, Query, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.web.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy import select, update, func, delete

from app.database.core import get_db
from app.database.models import User, Product, Category, CartItem, Order, OrderItem, UserAddress, Favorite, OrderRateLimit, PromoCode, PromoBanner, StockNotification, ProductImage, SupportChat, SupportMessage, promo_banner_products
from app.config import settings
from app.bot.loader import bot
from app.utils.security import check_telegram_auth
from app.utils.payment import generate_payme_link, generate_click_link

from app.utils.csrf import generate_csrf_token, validate_csrf, validate_csrf_header
from app.utils.file_manager import delete_file
from app.web.schemas.orders import OrderCreateSchema
from app.database.repositories.users import UserRepository
from app.database.repositories.products import ProductRepository
from app.database.repositories.orders import OrderRepository
from app.database.repositories.cart import CartRepository
from app.services.app_settings import (
    find_delivery_option,
    get_card_transfer_details,
    get_delivery_options,
    get_min_order_quantity_for_product,
    get_pickup_address,
    get_pickup_enabled,
    get_shop_all_products_image,
)
from app.services.order_service import OrderService
from app.utils.logger import logger
from app.utils.i18n import tr, get_js_translations
from app.utils.product_media import generate_video_poster, public_media_exists
from app.utils.payment_receipts import save_payment_receipt
from app.utils.upload_security import read_upload_limited, validate_image_upload
from app.utils.deeplinks import phone_registration_start_link

router = APIRouter(prefix="/shop", tags=["shop"])
templates = Jinja2Templates(directory="app/templates")

from datetime import timedelta as _timedelta
def _format_datetime_uz(value, format="%d.%m.%Y %H:%M"):
    if value is None:
        return ""
    local_dt = value + _timedelta(hours=5)
    return local_dt.strftime(format)

templates.env.filters["datetime_uz"] = _format_datetime_uz

def _format_number(value):
    try:
        return f"{int(value):,}".replace(",", " ")
    except (ValueError, TypeError):
        return value

templates.env.filters["number_format"] = _format_number

def _support_image_url(path):
    """Convert 'media/support/abc.jpg' to authenticated route '/shop/support/image/abc.jpg'."""
    if not path:
        return path
    fname = path.replace("\\", "/").split("/")[-1]
    return f"/shop/support/image/{fname}"

templates.env.filters["support_image_url"] = _support_image_url
templates.env.globals["tr"] = tr
templates.env.globals["get_js_translations"] = get_js_translations
templates.env.globals["phone_registration_start_link"] = phone_registration_start_link


def _format_location_address(data: dict) -> str:
    address = data.get("address") or {}
    parts = [
        address.get("road"),
        address.get("house_number"),
        address.get("neighbourhood") or address.get("suburb"),
        address.get("city") or address.get("town") or address.get("village"),
        address.get("state"),
    ]
    compact = ", ".join(str(part).strip() for part in parts if part)
    return compact or (data.get("display_name") or "").strip()


def _safe_shop_redirect_target(target: str, request: Request) -> str:
    fallback = "/shop"
    raw_target = (target or "").strip()
    if not raw_target:
        raw_target = (request.headers.get("referer") or "").strip()
    if not raw_target:
        return fallback

    parsed = urlparse(raw_target)
    if parsed.scheme or parsed.netloc:
        if parsed.netloc != request.url.netloc:
            return fallback
        redirect_to = parsed.path or fallback
        if parsed.query:
            redirect_to = f"{redirect_to}?{parsed.query}"
    else:
        redirect_to = raw_target

    parsed_redirect = urlparse(redirect_to)
    if not redirect_to.startswith("/") or redirect_to.startswith("//"):
        return fallback
    if parsed_redirect.path == "/shop/set_lang":
        return fallback
    if parsed_redirect.path != "/shop" and not parsed_redirect.path.startswith("/shop/"):
        return fallback
    return redirect_to

async def check_rate_limit(
    user_id: int,
    session: AsyncSession,
    cooldown_seconds: int = 10,
) -> bool:
    """Returns True if user is rate limited (should block), False if OK."""
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=cooldown_seconds)
    key = f"order_rate_limit:{user_id}"

    stmt = select(OrderRateLimit).where(OrderRateLimit.key == key)
    rate_limit = (await session.execute(stmt)).scalar_one_or_none()

    if rate_limit and rate_limit.expires_at > now:
        return True

    try:
        upsert_stmt = (
            insert(OrderRateLimit)
            .values(key=key, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=[OrderRateLimit.key],
                set_={"expires_at": expires_at},
            )
        )
        await session.execute(upsert_stmt)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return True

    return False

async def reset_rate_limit(user_id: int, session: AsyncSession) -> None:
    key = f"order_rate_limit:{user_id}"
    stmt = select(OrderRateLimit).where(OrderRateLimit.key == key)
    rate_limit = (await session.execute(stmt)).scalar_one_or_none()
    if rate_limit:
        await session.delete(rate_limit)
        await session.commit()

@router.post("/auth")
async def auth_user(request: Request, initData: str = Form(...), session: AsyncSession = Depends(get_db)):
    tg_user = check_telegram_auth(initData)
    
    if not tg_user:
        return JSONResponse({"status": "error", "message": "Invalid hash"}, status_code=403)
    
    tg_id = tg_user['id']
    
    user_repo = UserRepository(session)
    stmt = (
        insert(User)
        .values(telegram_id=tg_id, username=tg_user.get('username'), role="user")
        .on_conflict_do_nothing(index_elements=[User.telegram_id])
    )
    await session.execute(stmt)
    await session.commit()
    user = None
    for attempt in range(2):
        user = await user_repo.get_by_telegram_id(tg_id)
        if user:
            break
        if attempt == 0:
            await asyncio.sleep(0.1)
    if not user:
        raise HTTPException(status_code=503, detail="Qayta urinib ko'ring / Повторите попытку")

    updated_profile = False

    phone_value = tg_user.get("phone_number") or tg_user.get("phone")
    if phone_value:
        phone_value = re.sub(r'[^\d]', '', phone_value.strip())
        if phone_value and user.phone != phone_value:
            user.phone = phone_value
            updated_profile = True

    if updated_profile:
        await session.commit()

    request.session["shop_user_id"] = user.id
    request.session["shop_telegram_id"] = tg_id
    request.session["shop_init_data"] = initData
    return {"status": "ok"}

async def get_shop_user(request: Request, session: AsyncSession = Depends(get_db)):
    user_id = request.session.get("shop_user_id")
    session_telegram_id = request.session.get("shop_telegram_id")
    
    if not user_id or not session_telegram_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    stmt = select(User).options(selectinload(User.addresses)).where(User.id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    
    if not user or user.telegram_id != session_telegram_id:
         request.session.pop("shop_user_id", None)
         request.session.pop("shop_telegram_id", None)
         request.session.pop("shop_init_data", None)
         raise HTTPException(status_code=401, detail="User not found")
         
    return user

async def _get_favorite_ids(user_id: int, session: AsyncSession) -> set:
    stmt = select(Favorite.product_id).where(Favorite.user_id == user_id)
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)

@router.get("/", response_class=HTMLResponse)
async def shop_index(request: Request, session: AsyncSession = Depends(get_db)):
    try:
        user = await get_shop_user(request, session)
    except HTTPException:
        return templates.TemplateResponse("shop/auth_loader.html", {"request": request})

    start_param = (
        request.query_params.get("tgWebAppStartParam")
        or request.query_params.get("startapp")
        or request.query_params.get("start_param")
        or ""
    )
    if re.fullmatch(r"(product|category)_\d+", start_param):
        return RedirectResponse(f"/shop/deeplink/{start_param}", status_code=303)

    if not request.session.get("shop_categories_opened_first") and request.query_params.get("from_startapp") != "1":
        request.session["shop_categories_opened_first"] = True
        return RedirectResponse("/shop/categories", status_code=303)

    categories = (
        await session.execute(
            select(Category).where(Category.is_active == True).order_by(Category.sort_order.asc(), Category.id.asc())
        )
    ).scalars().all()

    # Page 1 of products for the grid (consistent with API pagination)
    page_limit = 20
    product_stmt = (
        select(Product)
        .join(Category, Category.id == Product.category_id)
        .where(Product.is_active == True, Category.is_active == True)
        .order_by(Product.id.desc())
        .limit(page_limit)
    )
    products = (await session.execute(product_stmt)).scalars().all()

    # Total count for has_more
    total_count = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .join(Category, Category.id == Product.category_id)
            .where(Product.is_active == True, Category.is_active == True)
        )
    ).scalar() or 0
    has_more = total_count > page_limit

    favorite_ids = await _get_favorite_ids(user.id, session)

    # Promo banners from DB
    banners_stmt = (
        select(PromoBanner)
        .options(selectinload(PromoBanner.products))
        .where(PromoBanner.is_active == True)
        .order_by(PromoBanner.sort_order.asc())
        .limit(5)
    )
    banners = (await session.execute(banners_stmt)).scalars().all()
    popular_products = (
        await session.execute(
            select(Product)
            .join(Category, Category.id == Product.category_id)
            .where(
                Product.is_active == True,
                Product.is_popular == True,
                Category.is_active == True,
            )
            .order_by(Product.popular_sort_order.asc(), Product.id.desc())
            .limit(10)
        )
    ).scalars().all()

    csrf_token = generate_csrf_token(request)

    return templates.TemplateResponse("shop/index.html", {
        "request": request, "user": user, "categories": categories, "products": products,
        "csrf_token": csrf_token, "favorite_ids": favorite_ids, "banners": banners,
        "popular_products": popular_products,
        "has_more": has_more,
    })


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    session: AsyncSession = Depends(get_db),
):
    try:
        user = await get_shop_user(request, session)
    except HTTPException:
        return templates.TemplateResponse("shop/auth_loader.html", {"request": request})

    search_query = (q or "").strip()
    page_limit = 20
    products: list[Product] = []
    total = 0
    has_more = False

    if search_query:
        product_repo = ProductRepository(session)
        products, total = await product_repo.get_filtered(
            query=search_query,
            limit=page_limit,
            offset=0,
        )
        has_more = total > page_limit

    favorite_ids = await _get_favorite_ids(user.id, session)
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/search.html", {
        "request": request,
        "user": user,
        "products": products,
        "favorite_ids": favorite_ids,
        "csrf_token": csrf_token,
        "search_query": search_query,
        "total": total,
        "has_more": has_more,
    })

@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request, session: AsyncSession = Depends(get_db)):
    try:
        user = await get_shop_user(request, session)
    except HTTPException:
        return templates.TemplateResponse("shop/auth_loader.html", {"request": request})

    request.session["shop_categories_opened_first"] = True

    stmt = (
        select(Category)
        .options(selectinload(Category.products))
        .where(Category.is_active == True)
        .order_by(Category.sort_order.asc(), Category.id.asc())
    )
    categories = (await session.execute(stmt)).scalars().all()
    all_products_image_path = await get_shop_all_products_image(session)
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/categories.html", {
        "request": request,
        "user": user,
        "categories": categories,
        "all_products_image_path": all_products_image_path,
        "csrf_token": csrf_token,
    })

@router.get("/category/{category_id}", response_class=HTMLResponse)
async def category_products_page(
    request: Request, category_id: int,
    session: AsyncSession = Depends(get_db),
):
    try:
        user = await get_shop_user(request, session)
    except HTTPException:
        return templates.TemplateResponse("shop/auth_loader.html", {"request": request})

    category = (await session.execute(
        select(Category).where(Category.id == category_id, Category.is_active == True)
    )).scalar_one_or_none()
    if not category:
        return RedirectResponse("/shop/categories", status_code=303)

    product_repo = ProductRepository(session)
    products = await product_repo.get_by_category(category_id)
    favorite_ids = await _get_favorite_ids(user.id, session)
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/category_products.html", {
        "request": request, "user": user, "category": category,
        "products": products, "csrf_token": csrf_token, "favorite_ids": favorite_ids,
    })


@router.get("/banner/{banner_id}", response_class=HTMLResponse)
async def banner_products_page(
    request: Request,
    banner_id: int,
    session: AsyncSession = Depends(get_db),
):
    try:
        user = await get_shop_user(request, session)
    except HTTPException:
        return templates.TemplateResponse("shop/auth_loader.html", {"request": request})

    banner = (
        await session.execute(
            select(PromoBanner)
            .where(PromoBanner.id == banner_id, PromoBanner.is_active == True)
        )
    ).scalar_one_or_none()
    if not banner:
        return RedirectResponse("/shop", status_code=303)

    products = (
        await session.execute(
            select(Product)
            .join(promo_banner_products, promo_banner_products.c.product_id == Product.id)
            .join(Category, Category.id == Product.category_id)
            .where(
                promo_banner_products.c.banner_id == banner_id,
                Product.is_active == True,
                Category.is_active == True,
            )
            .order_by(Product.id.desc())
        )
    ).scalars().all()
    favorite_ids = await _get_favorite_ids(user.id, session)
    csrf_token = generate_csrf_token(request)
    page_title = banner.title or banner.subtitle or tr("popular", user.language)
    return templates.TemplateResponse("shop/category_products.html", {
        "request": request,
        "user": user,
        "category": {"name_ru": page_title, "name_uz": page_title},
        "page_title": page_title,
        "back_url": "/shop",
        "products": products,
        "csrf_token": csrf_token,
        "favorite_ids": favorite_ids,
    })

@router.get("/set_lang")
async def set_language(
    request: Request,
    lang: str,
    next_url: str = Query("", alias="next"),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db),
):
    if lang in ["ru", "uz"]:
        user.language = lang
        await session.commit()
    request.session["shop_categories_opened_first"] = True
    return RedirectResponse(_safe_shop_redirect_target(next_url, request), status_code=303)

@router.get("/cart", response_class=HTMLResponse)
async def view_cart(request: Request, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    await OrderService.cancel_expired_online_orders(session, user_id=user.id)
    cart_repo = CartRepository(session)
    cart_items = await cart_repo.get_by_user(user.id)
    reserved_quantities = await OrderService.get_pending_online_reserved_quantities(
        session,
        user.id,
        [item.product_id for item in cart_items],
    )
    
    # Logic to handle ghost items
    final_items = []
    items_to_delete = []
    removed_inactive = request.query_params.get("removed") == "1"
    stock_adjusted = request.query_params.get("stock_adjusted") == "1"
    
    for item in cart_items:
        if not item.product:
            items_to_delete.append(item)
            removed_inactive = True
        else:
            if not item.product.is_active:
                items_to_delete.append(item)
                removed_inactive = True
            else:
                item.available_stock = (item.product.stock or 0) + reserved_quantities.get(item.product_id, 0)
                item.min_order_quantity = get_min_order_quantity_for_product(item.product)
                if item.available_stock >= item.min_order_quantity and item.quantity < item.min_order_quantity:
                    item.quantity = item.min_order_quantity
                    stock_adjusted = True
                elif item.available_stock >= item.min_order_quantity and item.quantity > item.available_stock:
                    item.quantity = item.available_stock
                    stock_adjusted = True
                # Monkey-patch unavailable flag for template
                item.unavailable = item.available_stock < item.min_order_quantity
                final_items.append(item)

    if items_to_delete or stock_adjusted:
        for i in items_to_delete:
            await session.delete(i)
        await session.commit()
    
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(
        "shop/cart.html",
        {
            "request": request,
            "user": user,
            "cart_items": final_items,
            "csrf_token": csrf_token,
            "removed_inactive": removed_inactive,
            "stock_adjusted": stock_adjusted,
        },
    )

@router.get("/api/cart/count")
async def get_cart_count(user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    await OrderService.cancel_expired_online_orders(session, user_id=user.id)
    stmt = select(func.sum(CartItem.quantity)).where(CartItem.user_id == user.id)
    count = (await session.execute(stmt)).scalar() or 0
    return {"count": count}

@router.post("/api/cart/add/{product_id}", dependencies=[Depends(validate_csrf_header)])
async def add_to_cart(product_id: int, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    # Проверяем, есть ли товар вообще
    product_repo = ProductRepository(session)
    product = await product_repo.get_visible_by_id(product_id)
    if not product or product.stock <= 0:
         return JSONResponse({"success": False, "message": tr("out_of_stock", user.language)}, status_code=400)
    min_order_quantity = get_min_order_quantity_for_product(product)

    cart_repo = CartRepository(session)
    try:
        existing = await cart_repo.get_item(user.id, product_id)
        reserved_quantity = (
            await OrderService.get_pending_online_reserved_quantities(session, user.id, [product_id])
        ).get(product_id, 0)
        available_stock = (product.stock or 0) + reserved_quantity
        if available_stock < min_order_quantity:
            return JSONResponse(
                {
                    "success": False,
                    "message": tr("min_product_quantity", user.language).replace("{quantity}", str(min_order_quantity)),
                },
                status_code=400,
            )

        if existing:
            new_quantity = max((existing.quantity or 0) + 1, min_order_quantity)
            # Проверяем, не превышает ли лимит на складе
            if new_quantity > available_stock:
                return JSONResponse(
                    {"success": False, "message": tr("out_of_stock", user.language)},
                    status_code=400,
                )

            await OrderService.cancel_pending_online_orders(
                session,
                user.id,
                product_id=product_id,
                commit=False,
                remove_cart_items=False,
            )

            # Atomic update to prevent race conditions
            stmt_update = (
                update(CartItem)
                .where(
                    CartItem.id == existing.id,
                    CartItem.quantity == existing.quantity,
                )
                .values(quantity=new_quantity)
            )
            result = await session.execute(stmt_update)
            if result.rowcount == 0:
                await session.rollback()
                return JSONResponse(
                    {"success": False, "message": tr("retry", user.language)},
                    status_code=409,
                )
        else:
            session.add(CartItem(user_id=user.id, product_id=product_id, quantity=min_order_quantity))

        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await cart_repo.get_item(user.id, product_id)
        reserved_quantity = (
            await OrderService.get_pending_online_reserved_quantities(session, user.id, [product_id])
        ).get(product_id, 0)
        available_stock = (product.stock or 0) + reserved_quantity
        if not existing or available_stock < min_order_quantity:
            return JSONResponse(
                {
                    "success": False,
                    "message": tr("min_product_quantity", user.language).replace("{quantity}", str(min_order_quantity)),
                },
                status_code=400,
            )
        new_quantity = max((existing.quantity or 0) + 1, min_order_quantity)
        if new_quantity > available_stock:
            new_quantity = available_stock
        await OrderService.cancel_pending_online_orders(
            session,
            user.id,
            product_id=product_id,
            commit=False,
            remove_cart_items=False,
        )
        stmt_update = (
            update(CartItem)
            .where(
                CartItem.id == existing.id,
                CartItem.quantity == existing.quantity,
            )
            .values(quantity=new_quantity)
        )
        await session.execute(stmt_update)
        await session.commit()
    count_stmt = select(CartItem).where(CartItem.user_id == user.id)
    items = (await session.execute(count_stmt)).scalars().all()
    return {"success": True, "total_count": sum(i.quantity for i in items)}

@router.post("/api/cart/update/{item_id}", dependencies=[Depends(validate_csrf_header)])
async def update_cart_qty(item_id: int, qty: int, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    cart_repo = CartRepository(session)
    item = await cart_repo.get_by_id_and_user(item_id, user.id)

    if not item or item.product is None:
        if item:
            await session.delete(item)
            await session.commit()
        return JSONResponse({"success": False, "message": tr("product_not_found", user.language)}, status_code=400)
    if qty <= 0:
        await OrderService.cancel_pending_online_orders(
            session,
            user.id,
            product_id=item.product_id,
            commit=False,
            remove_cart_items=False,
        )
        await session.delete(item)
        await session.commit()
        count_stmt = select(CartItem).where(CartItem.user_id == user.id)
        items = (await session.execute(count_stmt)).scalars().all()
        return {"success": True, "total_count": sum(i.quantity for i in items)}
    if not item.product.is_active:
        return JSONResponse({"success": False, "message": tr("out_of_stock", user.language)}, status_code=400)

    if item and qty > 0:
        min_order_quantity = get_min_order_quantity_for_product(item.product)
        reserved_quantity = (
            await OrderService.get_pending_online_reserved_quantities(session, user.id, [item.product_id])
        ).get(item.product_id, 0)
        available_stock = (item.product.stock or 0) + reserved_quantity
        if available_stock < min_order_quantity:
             return JSONResponse(
                 {
                     "success": False,
                     "message": tr("min_product_quantity", user.language).replace("{quantity}", str(min_order_quantity)),
                 },
                 status_code=400,
             )
        if qty < min_order_quantity:
             return JSONResponse(
                 {
                     "success": False,
                     "message": tr("min_product_quantity", user.language).replace("{quantity}", str(min_order_quantity)),
                 },
                 status_code=400,
             )
        if qty > available_stock:
             return JSONResponse({"success": False, "message": tr("not_enough_stock_api", user.language)}, status_code=400)

        if qty != item.quantity:
            await OrderService.cancel_pending_online_orders(
                session,
                user.id,
                product_id=item.product_id,
                commit=False,
                remove_cart_items=False,
            )
        
        # Atomic update
        stmt = (
            update(CartItem)
            .where(
                CartItem.id == item_id,
                CartItem.quantity == item.quantity,
            )
            .values(quantity=qty)
        )
        result = await session.execute(stmt)
        if result.rowcount == 0:
            await session.rollback()
            return JSONResponse(
                {"success": False, "message": tr("retry", user.language)},
                status_code=409,
            )
        await session.commit()
    return {"success": True}

@router.post("/api/cart/delete/{item_id}", dependencies=[Depends(validate_csrf_header)])
async def delete_cart_item(item_id: int, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    cart_repo = CartRepository(session)
    item = await cart_repo.get_by_id_and_user(item_id, user.id)
    if item:
        await OrderService.cancel_pending_online_orders(
            session,
            user.id,
            product_id=item.product_id,
            commit=False,
            remove_cart_items=False,
        )
        await session.delete(item)
        await session.commit()
    return {"success": True}

@router.get("/favorites", response_class=HTMLResponse)
async def view_favorites(request: Request, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    stmt = (
        select(Product)
        .join(Favorite)
        .join(Category, Category.id == Product.category_id)
        .where(Favorite.user_id == user.id, Product.is_active == True, Category.is_active == True)
    )
    products = (await session.execute(stmt)).scalars().all()
    favorite_ids = {p.id for p in products}
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/favorites.html", {"request": request, "user": user, "products": products, "csrf_token": csrf_token, "favorite_ids": favorite_ids})

@router.post("/api/favorite/{product_id}", dependencies=[Depends(validate_csrf_header)])
async def toggle_favorite(product_id: int, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.product_id == product_id)
    fav = (await session.execute(stmt)).scalar_one_or_none()
    added = False
    if fav:
        await session.delete(fav)
    else:
        session.add(Favorite(user_id=user.id, product_id=product_id))
        added = True
    await session.commit()
    return {"success": True, "added": added}


@router.get("/api/reverse-geocode")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    user: User = Depends(get_shop_user),
):
    params = {
        "format": "jsonv2",
        "lat": f"{lat:.6f}",
        "lon": f"{lon:.6f}",
        "addressdetails": "1",
        "accept-language": user.language or "ru",
    }
    headers = {
        "User-Agent": "UnicomMarket/1.0 (https://unicombot.uz)",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
            async with client.get("https://nominatim.openstreetmap.org/reverse", params=params) as response:
                if response.status != 200:
                    logger.warning(f"Reverse geocode failed with status {response.status}")
                    return JSONResponse({"address": "", "lat": lat, "lon": lon})
                data = await response.json()
    except Exception:
        logger.exception("Reverse geocode request failed")
        return JSONResponse({"address": "", "lat": lat, "lon": lon})

    return JSONResponse({
        "address": _format_location_address(data),
        "lat": lat,
        "lon": lon,
    })


@router.get("/checkout", response_class=HTMLResponse)
async def checkout_page(request: Request, items: List[int] = Query(None), user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    if not items: return RedirectResponse("/shop/cart")
    normalized_items = list(dict.fromkeys(items))
    if not normalized_items:
        return RedirectResponse("/shop/cart")
    await OrderService.cancel_expired_online_orders(session, user_id=user.id)
    cart_repo = CartRepository(session)
    selected_items = await cart_repo.get_items_by_ids(normalized_items, user.id)
    if not selected_items: return RedirectResponse("/shop/cart")
    if len(selected_items) != len(normalized_items):
        return RedirectResponse("/shop/cart", status_code=303)
    unavailable_items = [
        item
        for item in selected_items
        if not item.product or not item.product.is_active
    ]
    if unavailable_items:
        for item in unavailable_items:
            await session.delete(item)
        await session.commit()
        return RedirectResponse("/shop/cart?removed=1", status_code=303)
    stock_adjusted = False
    reserved_quantities = await OrderService.get_pending_online_reserved_quantities(
        session,
        user.id,
        [item.product_id for item in selected_items],
    )
    for item in selected_items:
        product_stock = item.product.stock if item.product and item.product.stock is not None else 0
        available_stock = product_stock + reserved_quantities.get(item.product_id, 0)
        min_order_quantity = get_min_order_quantity_for_product(item.product)
        if available_stock < min_order_quantity:
            stock_adjusted = True
            await session.delete(item)
        elif item.quantity < min_order_quantity:
            stock_adjusted = True
            item.quantity = min_order_quantity
        elif item.quantity > available_stock:
            stock_adjusted = True
            item.quantity = available_stock
    if stock_adjusted:
        await session.commit()
        return RedirectResponse("/shop/cart?stock_adjusted=1", status_code=303)
    product_total = sum(item.product.effective_price * item.quantity for item in selected_items)
    total_count = sum(item.quantity for item in selected_items)
    pickup_enabled = await get_pickup_enabled(session)
    pickup_address = await get_pickup_address(session)
    delivery_options = await get_delivery_options(session, active_only=True)
    card_transfer_details = await get_card_transfer_details(session)
    default_delivery = find_delivery_option(delivery_options, None)
    initial_delivery_price = 0 if pickup_enabled else int((default_delivery or {}).get("price") or 0)
    total_amount = product_total + initial_delivery_price

    # Saved addresses
    addr_stmt = select(UserAddress).where(UserAddress.user_id == user.id).order_by(UserAddress.id.desc()).limit(5)
    saved_addresses = (await session.execute(addr_stmt)).scalars().all()

    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/checkout.html", {
        "request": request, "user": user, "item_ids": normalized_items,
        "product_total": product_total, "delivery_price": initial_delivery_price,
        "total_amount": total_amount, "total_count": total_count,
        "pickup_enabled": pickup_enabled, "pickup_address": pickup_address,
        "delivery_options": delivery_options,
        "card_transfer_details": card_transfer_details,
        "csrf_token": csrf_token, "saved_addresses": saved_addresses
    })
     

@router.post("/order/create", dependencies=[Depends(validate_csrf_header)])
async def create_order(
    request: Request,
    order_data: OrderCreateSchema = Depends(OrderCreateSchema.as_form),
    payment_receipt: UploadFile = File(None),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    # Rate Limiting: не более 1 заказа в 10 секунд
    if await check_rate_limit(user.id, session, cooldown_seconds=10):
        pending_online_order = (
            await session.execute(
                select(Order.id)
                .where(
                    Order.user_id == user.id,
                    Order.status == "new",
                    Order.order_type == "product",
                    Order.payment_method.in_(OrderService.ONLINE_PAYMENT_METHODS),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not pending_online_order:
            return JSONResponse({"status": "error", "message": tr("order_create_error", user.language)}, status_code=429)
    
    payment_receipt_path = None
    try:
        if order_data.payment_method == "card_transfer":
            try:
                payment_receipt_path = await save_payment_receipt(payment_receipt)
            except ValueError as exc:
                if str(exc) == "file_too_large":
                    message = tr("payment_receipt_too_large", user.language)
                elif str(exc) == "receipt_required":
                    message = tr("payment_receipt_required", user.language)
                else:
                    message = tr("payment_receipt_invalid", user.language)
                await reset_rate_limit(user.id, session)
                return JSONResponse({"status": "error", "message": message}, status_code=400)

        result = await OrderService.create_order(
            user,
            order_data,
            session,
            payment_receipt_path=payment_receipt_path,
        )
        
        # Если метод оплаты click
        if order_data.payment_method == "click":
            # order_service возвращает JSONResponse с ID заказа, но нам нужно перехватить
            # В данном случае OrderService.create_order возвращает dict, если посмотреть код в сервисе?
            # Нет, в shop.py строка 246: return JSONResponse(result)
            # Значит result это dict.

            # ВАЖНО: OrderService.create_order возвращает dict, например {"status": "success", "order_id": 123}
            # Если status == success, то генерим ссылку.
            
            if result.get("status") == "success":
                order_id = result.get("order_id")
                # Нужно получить сумму заказа. result может не содержать сумму.
                # Лучше запросить заказ или изменить сервис.
                # Но чтобы не менять сервис, запросим заказ.
                stmt = select(Order).where(Order.id == order_id)
                new_order = (await session.execute(stmt)).scalar_one()
                
                click_url = generate_click_link(new_order.id, new_order.total_amount)
                
                # Уведомление
                try:
                    msg = tr("bot_order_created_click", user.language).replace("{order_id}", str(new_order.id)).replace("{amount}", f"{new_order.total_amount:,}")
                    if user.telegram_id:
                        await bot.send_message(user.telegram_id, msg, parse_mode="HTML")
                except Exception:
                    logger.exception("Failed to send Click order notification")
                
                return JSONResponse({"status": "redirect", "url": click_url})

        if result.get("status") not in {"success", "redirect"}:
            if payment_receipt_path:
                await delete_file(payment_receipt_path)
            await reset_rate_limit(user.id, session)

        return JSONResponse(result)
    except HTTPException as e:
        if payment_receipt_path:
            await delete_file(payment_receipt_path)
        await reset_rate_limit(user.id, session)
        return JSONResponse({"status": "error", "message": e.detail}, status_code=e.status_code)
    except Exception:
        logger.exception("Order creation error")
        if payment_receipt_path:
            await delete_file(payment_receipt_path)
        await reset_rate_limit(user.id, session)
        return JSONResponse({"status": "error", "message": tr("order_create_error", user.language)}, status_code=500)

@router.post("/order/pay_debt", dependencies=[Depends(validate_csrf)])
async def create_debt_payment(
    request: Request,
    amount: int = Form(...),
    payment_method: str = Form(...),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    if not user.debt or user.debt <= 0:
         return JSONResponse({"status": "error", "message": tr("error", user.language)}, status_code=400)
         
    if amount <= 0:
        raise HTTPException(status_code=400, detail=tr("error", user.language))

    # Проверка суммы погашения (нельзя оплатить больше, чем долг)
    if user.debt and amount > user.debt:
        return JSONResponse({"status": "error", "message": tr("debt_exceeds", user.language)}, status_code=400)
    
    # Extra safety: Ensure debt is strictly positive
    if not user.debt or user.debt <= 0:
         return JSONResponse({"status": "error", "message": tr("error", user.language)}, status_code=400)

    # Check for existing unpaid debt order
    existing_debt_stmt = select(Order).where(
        Order.user_id == user.id,
        Order.order_type == "debt_repayment",
        Order.status == "new",
    )
    existing_debt = (await session.execute(existing_debt_stmt)).scalar_one_or_none()
    if existing_debt:
        await OrderService.cancel_order(session, existing_debt.id)

    payment_method_value = payment_method.strip().lower()
    allowed_methods = {"card", "click"}
    if payment_method_value not in allowed_methods:
        return JSONResponse(
            {"status": "error", "message": tr("error", user.language)},
            status_code=400,
        )

    # Создаем заказ на погашение долга
    new_order = Order(
        user_id=user.id,
        status="new",
        order_type="debt_repayment",
        payment_method=payment_method_value,
        delivery_method="pickup",
        delivery_address=None,
        total_amount=amount,
        comment=tr("debt_repayment_comment", user.language),
        contact_phone=user.phone or ""
    )
    session.add(new_order)
    await session.commit()

    if payment_method_value == "click":
        pay_url = generate_click_link(new_order.id, amount)
    else:
        pay_url = generate_payme_link(new_order.id, amount)
    return JSONResponse({"status": "redirect", "url": pay_url})

@router.get("/order/success/{order_id}", response_class=HTMLResponse)
async def order_success_page(request: Request, order_id: int, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    # IDOR Check: Ensure order belongs to user
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    
    if not order:
        return RedirectResponse("/shop/profile")

    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/order_success.html", {
        "request": request,
        "user": user,
        "order": order,
        "order_id": order_id,
        "csrf_token": csrf_token,
    })

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    await OrderService.cancel_expired_online_orders(session, user_id=user.id)
    stmt = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    orders = (await session.execute(stmt)).scalars().all()
    # Unread support messages count
    unread_support = 0
    chat_row = (await session.execute(
        select(SupportChat.unread_user).where(SupportChat.user_id == user.id)
    )).scalar_one_or_none()
    if chat_row:
        unread_support = chat_row
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(
        "shop/profile.html",
        {"request": request, "user": user, "orders": orders, "csrf_token": csrf_token, "unread_support": unread_support},
    )

@router.get("/profile/edit", response_class=HTMLResponse)
async def profile_edit_page(request: Request, user: User = Depends(get_shop_user)):
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(
        "shop/profile_edit.html",
        {"request": request, "user": user, "csrf_token": csrf_token},
    )

@router.post("/profile/update", dependencies=[Depends(validate_csrf)])
async def profile_update(
    request: Request,
    phone: str = Form(""),
    language: str = Form("ru"),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db),
):
    if language in ["ru", "uz"]:
        user.language = language
    phone_clean = re.sub(r'[^\d]', '', phone.strip())
    if phone_clean:
        if len(phone_clean) == 9:
            phone_clean = "998" + phone_clean
        if len(phone_clean) >= 9:
            user.phone = phone_clean
    await session.commit()
    return RedirectResponse("/shop/profile", status_code=303)

# ===================== ДЕТАЛИ ЗАКАЗА =====================
@router.get("/order/{order_id}", response_class=HTMLResponse)
async def order_detail_page(
    request: Request,
    order_id: int,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.promo_code))
        .where(Order.id == order_id, Order.user_id == user.id)
    )
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        return RedirectResponse("/shop/profile")

    csrf_token = generate_csrf_token(request)

    # Auto-cancel expired online orders
    if order.status == "new" and order.payment_method in ("card", "click"):
        if await OrderService.cancel_expired_online_order(session, order):
            await session.refresh(order)

    # Генерируем ссылку на оплату для неоплаченных онлайн-заказов
    payment_url = None
    if order.status == "new" and order.payment_method in ("card", "click"):
        if order.payment_method == "click":
            payment_url = generate_click_link(order.id, order.total_amount)
        else:
            payment_url = generate_payme_link(order.id, order.total_amount)

    return templates.TemplateResponse("shop/order_detail.html", {
        "request": request, "user": user, "order": order,
        "csrf_token": csrf_token, "payment_url": payment_url
    })

# ===================== КОМБИНИРОВАННЫЙ ПОИСК + КАТЕГОРИЯ =====================
@router.get("/api/products/filter")
async def filter_products(
    request: Request,
    q: str = "",
    category_id: str = "all",
    page: int = 1,
    limit: int = 20,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    offset = (max(page, 1) - 1) * limit
    category_filter = int(category_id) if category_id and category_id.isdigit() else None
    product_repo = ProductRepository(session)
    products, total = await product_repo.get_filtered(
        query=q,
        category_id=category_filter,
        limit=limit,
        offset=offset,
    )

    favorite_ids = await _get_favorite_ids(user.id, session)
    csrf_token = generate_csrf_token(request)

    has_more = (offset + limit) < total

    html = templates.TemplateResponse("shop/partials/product_list.html", {
        "request": request, "user": user, "products": products,
        "csrf_token": csrf_token, "favorite_ids": favorite_ids
    })

    return JSONResponse({
        "html": html.body.decode(),
        "has_more": has_more,
        "total": total,
        "page": page,
    })

# ===================== УВЕДОМЛЕНИЯ О НАЛИЧИИ =====================
@router.post("/api/stock-notify/{product_id}", dependencies=[Depends(validate_csrf_header)])
async def toggle_stock_notify(
    product_id: int,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    stmt = select(StockNotification).where(
        StockNotification.user_id == user.id,
        StockNotification.product_id == product_id
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing:
        await session.delete(existing)
        await session.commit()
        return {"success": True, "subscribed": False}
    else:
        session.add(StockNotification(user_id=user.id, product_id=product_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        return {"success": True, "subscribed": True}

# ===================== ДЕТАЛИ ТОВАРА (API) С МУЛЬТИФОТО =====================
@router.get("/api/product/{product_id}")
async def product_detail_api(
    product_id: int,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Product)
        .options(selectinload(Product.images))
        .join(Category, Category.id == Product.category_id)
        .where(Product.id == product_id, Category.is_active == True)
    )
    product = (await session.execute(stmt)).scalar_one_or_none()
    if not product or not product.is_active:
        return JSONResponse({"error": "Not found"}, status_code=404)

    # Build media list: [{src, type}, ...]
    media = []
    seen = set()
    poster_updated = False
    if product.image_path:
        media.append({"src": product.image_path, "type": "image"})
        seen.add(product.image_path)
    for img in sorted(product.images, key=lambda x: x.sort_order):
        if img.image_path and img.image_path not in seen:
            item = {"src": img.image_path, "type": img.media_type or "image"}
            if (img.media_type or "image") == "video":
                poster_path = img.poster_path
                if not public_media_exists(poster_path):
                    poster_path = await generate_video_poster(img.image_path, existing_poster_path=poster_path)
                    if poster_path and poster_path != img.poster_path:
                        img.poster_path = poster_path
                        poster_updated = True
                if poster_path:
                    item["poster"] = poster_path
            media.append(item)
            seen.add(img.image_path)

    if poster_updated:
        await session.commit()

    # Backward-compat: flat image list for older clients
    images = [m["src"] for m in media]

    # Check if user subscribed to stock notification
    notify_stmt = select(StockNotification).where(
        StockNotification.user_id == user.id,
        StockNotification.product_id == product_id,
        StockNotification.notified == False,
    )
    stock_subscribed = (await session.execute(notify_stmt)).scalar_one_or_none() is not None

    lang = user.language or "ru"
    return {
        "id": product.id,
        "name": product.name_ru if lang == "ru" else product.name_uz,
        "description": (product.description_ru if lang == "ru" else product.description_uz) or "",
        "price": product.effective_price,
        "regular_price": product.price,
        "discount_price": product.discount_price if product.has_discount else None,
        "has_discount": product.has_discount,
        "discount_percent": product.discount_percent,
        "stock": product.stock,
        "sell_type": product.sell_type or "piece",
        "pack_quantity": product.pack_quantity,
        "images": images,
        "media": media,
        "stock_subscribed": stock_subscribed,
    }

# ===================== ПРОМОКОД ВАЛИДАЦИЯ =====================
@router.post("/api/promo/validate", dependencies=[Depends(validate_csrf_header)])
async def validate_promo_code(
    request: Request,
    code: str = Form(""),
    total: int = Form(0),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    code = code.strip().upper()
    lang = user.language or "ru"
    if not code:
        return JSONResponse({"valid": False, "message": tr("enter_promo_code", lang)}, status_code=400)

    stmt = select(PromoCode).where(PromoCode.code == code, PromoCode.is_active == True)
    promo = (await session.execute(stmt)).scalar_one_or_none()

    if not promo:
        return JSONResponse({"valid": False, "message": tr("promo_not_found", lang)})

    now = datetime.utcnow()
    if promo.expires_at and promo.expires_at < now:
        return JSONResponse({"valid": False, "message": tr("promo_expired", lang)})

    if promo.usage_limit and promo.used_count >= promo.usage_limit:
        return JSONResponse({"valid": False, "message": tr("promo_exhausted", lang)})

    from app.database.models import UserPromoUsage
    existing_usage = (await session.execute(
        select(UserPromoUsage).where(UserPromoUsage.user_id == user.id, UserPromoUsage.promo_id == promo.id)
    )).scalar_one_or_none()
    if existing_usage:
        pending_promo_order = (
            await session.execute(
                select(Order.id)
                .where(
                    Order.user_id == user.id,
                    Order.status == "new",
                    Order.order_type == "product",
                    Order.payment_method.in_(OrderService.ONLINE_PAYMENT_METHODS),
                    Order.promo_code_id == promo.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not pending_promo_order:
            return JSONResponse({"valid": False, "message": tr("promo_already_used", lang)})

    if total < promo.min_order_amount:
        return JSONResponse({"valid": False, "message": tr("promo_min_order", lang).replace("{amount}", f"{promo.min_order_amount:,}")})

    if promo.discount_type == "percent":
        discount = int(total * promo.discount_value / 100)
        if promo.max_discount and discount > promo.max_discount:
            discount = promo.max_discount
    else:
        discount = promo.discount_value

    from app.config import settings
    max_allowed_discount = total - settings.MIN_ORDER_AMOUNT
    discount = min(discount, total, max(0, max_allowed_discount))
    new_total = total - discount

    return {
        "valid": True,
        "promo_id": promo.id,
        "discount": discount,
        "new_total": new_total,
        "message": tr("promo_applied", lang).replace("{discount}", f"{discount:,}"),
    }

# ===================== ОТМЕНА ЗАКАЗА (ПОЛЬЗОВАТЕЛЬ) =====================
@router.post("/api/order/{order_id}/cancel", dependencies=[Depends(validate_csrf_header)])
async def cancel_order_user(
    order_id: int,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db)
):
    stmt = select(Order).where(Order.id == order_id, Order.user_id == user.id)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        return JSONResponse({"success": False, "message": tr("error", user.language)}, status_code=404)

    if order.status != "new":
        return JSONResponse({"success": False, "message": tr("error", user.language)}, status_code=400)

    await OrderService.cancel_order(session, order_id)
    OrderService.notify_user_order_status(user, "cancelled")
    OrderService.notify_status_subscribers(order_id, "cancelled")

    return {"success": True}

# ===================== ПОДДЕРЖКА (ЧАТ) =====================
SUPPORT_UPLOAD_DIR = "media/support"
SUPPORT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
SUPPORT_MAX_TEXT_LENGTH = 4000

@router.get("/support/image/{filename}")
async def support_image(
    filename: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Serve support images with authentication check."""
    from starlette.responses import FileResponse

    # Must be logged in as shop user or admin
    shop_user_id = request.session.get("shop_user_id")
    admin_user_id = request.session.get("user_id")
    if not shop_user_id and not admin_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Sanitize filename to prevent path traversal
    safe_name = os.path.basename(filename)
    fpath = os.path.join(SUPPORT_UPLOAD_DIR, safe_name)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Not found")

    # If shop user, verify they own this image
    if shop_user_id and not admin_user_id:
        stmt = select(SupportMessage).where(
            SupportMessage.image_path == fpath.replace("\\", "/")
        ).options(selectinload(SupportMessage.chat))
        msg = (await session.execute(stmt)).scalar_one_or_none()
        if not msg:
            # Also try with forward slashes
            stmt2 = select(SupportMessage).where(
                SupportMessage.image_path == fpath
            ).options(selectinload(SupportMessage.chat))
            msg = (await session.execute(stmt2)).scalar_one_or_none()
        if not msg or msg.chat.user_id != shop_user_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    return FileResponse(fpath)

SUPPORT_PAGE_SIZE = 50

@router.get("/support", response_class=HTMLResponse)
async def support_page(request: Request, user: User = Depends(get_shop_user), session: AsyncSession = Depends(get_db)):
    stmt = select(SupportChat).where(SupportChat.user_id == user.id)
    chat = (await session.execute(stmt)).scalar_one_or_none()

    messages = []
    has_older = False
    if chat:
        chat.unread_user = 0
        await session.commit()
        # Load last N messages (newest last)
        msg_stmt = (
            select(SupportMessage)
            .where(SupportMessage.chat_id == chat.id)
            .order_by(SupportMessage.created_at.desc())
            .limit(SUPPORT_PAGE_SIZE + 1)
        )
        rows = list((await session.execute(msg_stmt)).scalars().all())
        if len(rows) > SUPPORT_PAGE_SIZE:
            has_older = True
            rows = rows[:SUPPORT_PAGE_SIZE]
        messages = list(reversed(rows))  # oldest first for display

    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse("shop/support.html", {
        "request": request, "user": user, "messages": messages,
        "csrf_token": csrf_token, "chat_id": chat.id if chat else None,
        "has_older": has_older,
        "oldest_id": messages[0].id if messages else 0,
    })

@router.post("/api/support/send")
async def support_send_message(
    request: Request,
    text: str = Form(""),
    image: UploadFile = File(None),
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db),
    csrf: bool = Depends(validate_csrf_header),
):
    text = text.strip()
    if len(text) > SUPPORT_MAX_TEXT_LENGTH:
        return JSONResponse({"error": "Message too long"}, status_code=400)

    image_path = None

    if image and image.filename:
        try:
            content = await read_upload_limited(image, SUPPORT_MAX_FILE_SIZE)
            ext = validate_image_upload(image.filename, content)
        except ValueError as exc:
            if str(exc) == "file_too_large":
                return JSONResponse({"error": tr("support_photo_too_large", user.language)}, status_code=400)
            return JSONResponse({"error": "Invalid image"}, status_code=400)
        if not content:
            return JSONResponse({"error": tr("support_photo_too_large", user.language)}, status_code=400)
        os.makedirs(SUPPORT_UPLOAD_DIR, exist_ok=True)
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = os.path.join(SUPPORT_UPLOAD_DIR, fname)
        async with aiofiles.open(fpath, "wb") as f:
            await f.write(content)
        image_path = fpath

    if not text and not image_path:
        return JSONResponse({"error": "empty"}, status_code=400)

    stmt = select(SupportChat).where(SupportChat.user_id == user.id)
    chat = (await session.execute(stmt)).scalar_one_or_none()
    if not chat:
        chat = SupportChat(user_id=user.id, is_closed=False)
        session.add(chat)
        await session.flush()

    msg = SupportMessage(
        chat_id=chat.id,
        sender_type="user",
        sender_id=user.id,
        text=text or None,
        image_path=image_path,
    )
    session.add(msg)
    chat.last_message_at = datetime.utcnow()
    chat.unread_admin += 1
    chat.is_closed = False
    await session.commit()

    return JSONResponse({
        "ok": True,
        "message": {
            "id": msg.id,
            "sender_type": "user",
            "text": msg.text,
            "image_path": f"/{msg.image_path}" if msg.image_path else None,
            "created_at": msg.created_at.strftime("%H:%M"),
        }
    })

@router.get("/api/support/unread")
async def support_unread_count(
    request: Request,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db),
):
    count = (await session.execute(
        select(SupportChat.unread_user).where(SupportChat.user_id == user.id)
    )).scalar_one_or_none()
    return {"unread": count or 0}

@router.get("/api/support/messages")
async def support_get_messages(
    request: Request,
    after: int = 0,
    before: int = 0,
    user: User = Depends(get_shop_user),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(SupportChat).where(SupportChat.user_id == user.id)
    chat = (await session.execute(stmt)).scalar_one_or_none()
    if not chat:
        return {"messages": [], "has_older": False}

    if before > 0:
        # Load older messages (for "load more" pagination)
        msg_stmt = (
            select(SupportMessage)
            .where(SupportMessage.chat_id == chat.id, SupportMessage.id < before)
            .order_by(SupportMessage.created_at.desc())
            .limit(SUPPORT_PAGE_SIZE + 1)
        )
        rows = list((await session.execute(msg_stmt)).scalars().all())
        has_older = len(rows) > SUPPORT_PAGE_SIZE
        if has_older:
            rows = rows[:SUPPORT_PAGE_SIZE]
        msgs = list(reversed(rows))
        return {
            "has_older": has_older,
            "messages": [
                {
                    "id": m.id,
                    "sender_type": m.sender_type,
                    "text": m.text,
                    "image_path": f"/{m.image_path}" if m.image_path else None,
                    "created_at": m.created_at.strftime("%H:%M"),
                }
                for m in msgs
            ]
        }

    # Default: poll for new messages after given ID
    if after > 0:
        chat.unread_user = 0
        await session.commit()

    msg_stmt = (
        select(SupportMessage)
        .where(SupportMessage.chat_id == chat.id, SupportMessage.id > after)
        .order_by(SupportMessage.created_at.asc())
    )
    msgs = (await session.execute(msg_stmt)).scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "sender_type": m.sender_type,
                "text": m.text,
                "image_path": f"/{m.image_path}" if m.image_path else None,
                "created_at": m.created_at.strftime("%H:%M"),
            }
            for m in msgs
        ]
    }
