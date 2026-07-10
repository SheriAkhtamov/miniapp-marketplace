"""
Payme Sandbox Test Helper — /test
Comprehensive testing dashboard for Payme sandbox.
REMOVE THIS FILE BEFORE GOING TO PRODUCTION!
"""
import base64
import time as time_mod
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.web.templating import Jinja2Templates
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.core import get_db
from app.database.models import (
    User, Product, Category, Order, OrderItem, PaymeTransaction,
)
from app.config import settings
from app.utils.logger import logger

router = APIRouter(prefix="/test", tags=["test"])
templates = Jinja2Templates(directory="app/templates")

TAG_PREFIX = "__pt_"

SCENARIOS = [
    {
        "tag": "__pt_invalid_data__",
        "label": "Тесты с неверными данными",
        "amount": 5000,
        "desc": "Неверная авторизация, неверная сумма, несуществующий счёт",
    },
    {
        "tag": "__pt_scenario2__",
        "label": "Создание + отмена неподтверждённой",
        "amount": 10000,
        "desc": "CheckPerformTransaction → CreateTransaction → CancelTransaction (state 1→-1)",
    },
    {
        "tag": "__pt_scenario3__",
        "label": "Создание + подтверждение + отмена",
        "amount": 15000,
        "desc": "CheckPerformTransaction → CreateTransaction → PerformTransaction → CancelTransaction (state 2→-2)",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_test_user(session: AsyncSession) -> User:
    """Get or create a test user for sandbox testing."""
    stmt = select(User).where(User.login == "__payme_test__")
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=None,
            username="PaymeTestUser",
            login="__payme_test__",
            phone="+998900000000",
            role="user",
        )
        session.add(user)
        await session.flush()
    return user


async def _ensure_test_product(session: AsyncSession) -> Product:
    """Get or create a test product for sandbox orders."""
    stmt = select(Product).where(Product.name_ru == "__PAYME_TEST_PRODUCT__")
    product = (await session.execute(stmt)).scalar_one_or_none()
    if not product:
        cat_stmt = select(Category).limit(1)
        category = (await session.execute(cat_stmt)).scalar_one_or_none()
        if not category:
            category = Category(name_ru="Тест", name_uz="Test")
            session.add(category)
            await session.flush()

        product = Product(
            category_id=category.id,
            name_ru="__PAYME_TEST_PRODUCT__",
            name_uz="__PAYME_TEST_PRODUCT__",
            price=1000,
            stock=9999,
            image_path="static/img/placeholder.png",
            is_active=False,
            ikpu="00702001001000001",
            package_code=settings.DEFAULT_PACKAGE_CODE,
        )
        session.add(product)
        await session.flush()
    return product


async def _create_order(session: AsyncSession, user: User, product: Product,
                        amount: int, tag: str) -> Order:
    """Create a single test order with the given tag."""
    order = Order(
        user_id=user.id,
        status="new",
        order_type="product",
        payment_method="card",
        delivery_method="pickup",
        total_amount=amount,
        contact_phone="+998900000000",
        comment=tag,
    )
    session.add(order)
    await session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=f"Тестовый товар ({amount} сум)",
        price_at_purchase=amount,
        quantity=1,
    )
    session.add(item)
    return order


def _payme_checkout_url(order_id: int, amount_sum: int) -> str:
    """Build Payme sandbox checkout URL."""
    amount_tiyin = amount_sum * 100
    params = f"m={settings.PAYME_ID};ac.{settings.PAYME_ACCOUNT_FIELD}={order_id};a={amount_tiyin}"
    params_b64 = base64.b64encode(params.encode("utf-8")).decode("utf-8")
    return f"{settings.PAYME_URL}/{params_b64}"


def _get_scenario_tags():
    return [s["tag"] for s in SCENARIOS]


def _order_to_dict(order: Order) -> dict:
    txs = sorted(order.payme_transactions, key=lambda t: t.id)
    return {
        "id": order.id,
        "amount": order.total_amount,
        "amount_tiyin": order.total_amount * 100,
        "status": order.status,
        "payment_method": order.payment_method,
        "created_at": order.created_at,
        "checkout_url": _payme_checkout_url(order.id, order.total_amount),
        "transactions": txs,
        "tag": order.comment,
    }


async def _load_all_test_orders(session: AsyncSession):
    """Load ALL test orders (scenario + custom)."""
    stmt = (
        select(Order)
        .where(Order.comment.like(f"{TAG_PREFIX}%"))
        .options(selectinload(Order.items), selectinload(Order.payme_transactions))
        .order_by(Order.id.desc())
    )
    return (await session.execute(stmt)).scalars().all()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def test_dashboard(request: Request, session: AsyncSession = Depends(get_db)):
    """Main test dashboard page."""
    scenario_tags = _get_scenario_tags()
    orders = await _load_all_test_orders(session)

    orders_by_tag = {}
    custom_orders = []
    for o in orders:
        od = _order_to_dict(o)
        if o.comment in scenario_tags:
            if o.comment not in orders_by_tag:
                orders_by_tag[o.comment] = od
        else:
            custom_orders.append(od)

    scenario_data = []
    for sc in SCENARIOS:
        order = orders_by_tag.get(sc["tag"])
        scenario_data.append({
            **sc,
            "order": order,
            "ready": order is not None and order["status"] == "new",
        })

    is_sandbox = "test" in settings.PAYME_URL.lower()
    has_all = all(s["order"] is not None for s in scenario_data)

    return templates.TemplateResponse("test/index.html", {
        "request": request,
        "scenarios": scenario_data,
        "custom_orders": custom_orders,
        "has_all": has_all,
        "is_sandbox": is_sandbox,
        "payme_url": settings.PAYME_URL,
        "payme_id": settings.PAYME_ID,
        "payme_key": settings.PAYME_KEY,
        "endpoint_url": f"{settings.WEB_BASE_URL}/api/payme",
        "account_field": settings.PAYME_ACCOUNT_FIELD,
    })


@router.post("/setup-all")
async def setup_all_scenarios(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """One-click: create fresh orders for ALL test scenarios."""
    user = await _ensure_test_user(session)
    product = await _ensure_test_product(session)
    scenario_tags = _get_scenario_tags()

    # Delete old scenario orders
    old_stmt = select(Order).where(Order.comment.in_(scenario_tags))
    old_orders = (await session.execute(old_stmt)).scalars().all()
    for old in old_orders:
        await session.execute(
            delete(PaymeTransaction).where(PaymeTransaction.order_id == old.id)
        )
        await session.execute(
            delete(OrderItem).where(OrderItem.order_id == old.id)
        )
        await session.delete(old)
    await session.flush()

    # Also clean up orders with legacy tags
    for legacy_tag in ["__pt_invalid_amount__"]:
        try:
            legacy_stmt = select(Order).where(Order.comment == legacy_tag)
            legacy_orders = (await session.execute(legacy_stmt)).scalars().all()
            for old in legacy_orders:
                await session.execute(delete(PaymeTransaction).where(PaymeTransaction.order_id == old.id))
                await session.execute(delete(OrderItem).where(OrderItem.order_id == old.id))
                await session.delete(old)
            await session.flush()
        except Exception:
            pass

    for sc in SCENARIOS:
        order = await _create_order(session, user, product, sc["amount"], sc["tag"])
        logger.info(
            f"[PaymeTest] Created order #{order.id} for '{sc['label']}', "
            f"amount={sc['amount']} sum ({sc['amount'] * 100} tiyin)"
        )

    await session.commit()
    return RedirectResponse(url="/test", status_code=303)


@router.post("/create-order")
async def create_custom_order(
    request: Request,
    amount: int = Form(...),
    session: AsyncSession = Depends(get_db),
):
    """Create a single custom test order with specified amount (in sum)."""
    if amount < 100:
        return RedirectResponse(url="/test", status_code=303)
    user = await _ensure_test_user(session)
    product = await _ensure_test_product(session)
    tag = f"{TAG_PREFIX}custom_{int(time_mod.time())}"
    order = await _create_order(session, user, product, amount, tag)
    logger.info(f"[PaymeTest] Created custom order #{order.id}, amount={amount} sum")
    await session.commit()
    return RedirectResponse(url="/test", status_code=303)


@router.post("/reset-order/{order_id}")
async def reset_test_order(
    order_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Reset a test order to 'new' status and delete its Payme transactions."""
    stmt = select(Order).where(Order.id == order_id, Order.comment.like(f"{TAG_PREFIX}%"))
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order:
        order.status = "new"
        order.payment_method = "card"
        await session.execute(
            delete(PaymeTransaction).where(PaymeTransaction.order_id == order_id)
        )
        await session.commit()
        logger.info(f"[PaymeTest] Reset order #{order_id}")

    return RedirectResponse(url="/test", status_code=303)


@router.post("/delete-order/{order_id}")
async def delete_test_order(
    order_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Delete a test order and its transactions/items."""
    stmt = select(Order).where(Order.id == order_id, Order.comment.like(f"{TAG_PREFIX}%"))
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order:
        await session.execute(
            delete(PaymeTransaction).where(PaymeTransaction.order_id == order_id)
        )
        await session.execute(
            delete(OrderItem).where(OrderItem.order_id == order_id)
        )
        await session.delete(order)
        await session.commit()
        logger.info(f"[PaymeTest] Deleted order #{order_id}")

    return RedirectResponse(url="/test", status_code=303)


@router.post("/delete-all")
async def delete_all_test_orders(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Delete ALL test orders (scenario + custom)."""
    orders = await _load_all_test_orders(session)
    for order in orders:
        await session.execute(
            delete(PaymeTransaction).where(PaymeTransaction.order_id == order.id)
        )
        await session.execute(
            delete(OrderItem).where(OrderItem.order_id == order.id)
        )
        await session.delete(order)
    await session.commit()
    logger.info(f"[PaymeTest] Deleted all {len(orders)} test orders")
    return RedirectResponse(url="/test", status_code=303)


@router.get("/api/status")
async def orders_status_api(session: AsyncSession = Depends(get_db)):
    """AJAX endpoint: current status of all test orders."""
    orders = await _load_all_test_orders(session)
    result = []
    for o in orders:
        txs = sorted(o.payme_transactions, key=lambda t: t.id)
        result.append({
            "id": o.id,
            "amount": o.total_amount,
            "amount_tiyin": o.total_amount * 100,
            "status": o.status,
            "tag": o.comment,
            "transactions": [
                {
                    "id": tx.id,
                    "payme_id": tx.payme_id,
                    "state": tx.state,
                    "amount": tx.amount,
                    "reason": tx.reason,
                }
                for tx in txs
            ],
        })
    return JSONResponse({"orders": result})
