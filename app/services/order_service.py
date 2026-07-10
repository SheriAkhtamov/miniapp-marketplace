from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.config import settings
from app.database.models import User, Product, Order, OrderItem, UserAddress, CartItem, PromoCode, UserPromoUsage
from app.web.schemas.orders import OrderCreateSchema
from app.database.repositories.cart import CartRepository
from app.bot.loader import bot
from app.services.app_settings import (
    find_delivery_option,
    get_delivery_options,
    get_min_order_quantity_for_product,
    get_pickup_address,
    get_pickup_enabled,
)
from app.utils.payment import generate_payme_link
from app.utils.logger import logger
from app.utils.i18n import tr


class OrderRestoreError(ValueError):
    """Raised when a cancelled order can no longer be restored safely."""


class OrderService:
    ONLINE_PAYMENT_METHODS = ("card", "click")

    @staticmethod
    def _online_payment_timeout_cutoff() -> datetime:
        timeout_minutes = getattr(settings, "ORDER_PAYMENT_TIMEOUT_MINUTES", 20)
        return datetime.utcnow() - timedelta(minutes=timeout_minutes)

    @staticmethod
    async def get_pending_online_reserved_quantities(
        session: AsyncSession,
        user_id: int,
        product_ids: Optional[List[int]] = None,
    ) -> Dict[int, int]:
        stmt = (
            select(OrderItem.product_id, func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.user_id == user_id,
                Order.status == "new",
                Order.order_type == "product",
                Order.payment_method.in_(OrderService.ONLINE_PAYMENT_METHODS),
                OrderItem.product_id.isnot(None),
            )
            .group_by(OrderItem.product_id)
        )
        if product_ids:
            stmt = stmt.where(OrderItem.product_id.in_(product_ids))

        rows = (await session.execute(stmt)).all()
        return {int(product_id): int(quantity or 0) for product_id, quantity in rows}

    @staticmethod
    async def remove_order_items_from_cart(
        session: AsyncSession,
        order: Order,
    ) -> None:
        if order.order_type != "product" or not order.user_id:
            return

        product_ids = (
            await session.execute(
                select(OrderItem.product_id)
                .where(
                    OrderItem.order_id == order.id,
                    OrderItem.product_id.isnot(None),
                )
                .distinct()
            )
        ).scalars().all()
        if not product_ids:
            return

        await session.execute(
            delete(CartItem).where(
                CartItem.user_id == order.user_id,
                CartItem.product_id.in_(product_ids),
            )
        )

    @staticmethod
    async def cancel_pending_online_orders(
        session: AsyncSession,
        user_id: int,
        product_id: Optional[int] = None,
        *,
        commit: bool = True,
        remove_cart_items: bool = False,
    ) -> List[int]:
        stmt = select(Order.id).where(
            Order.user_id == user_id,
            Order.status == "new",
            Order.order_type == "product",
            Order.payment_method.in_(OrderService.ONLINE_PAYMENT_METHODS),
        )
        if product_id is not None:
            stmt = stmt.join(OrderItem, OrderItem.order_id == Order.id).where(
                OrderItem.product_id == product_id
            )

        order_ids = (await session.execute(stmt.distinct())).scalars().all()
        for order_id in order_ids:
            await OrderService.cancel_order(
                session,
                order_id,
                commit=False,
                remove_cart_items=remove_cart_items,
            )

        if order_ids and commit:
            await session.commit()

        return order_ids

    @staticmethod
    def notify_user_order_status(user: Optional[User], status: str) -> None:
        """Send Telegram status update to a customer when supported."""
        if not user or not user.telegram_id:
            return

        user_lang = user.language or "ru"
        status_text = {
            "paid": tr("bot_status_paid", user_lang),
            "delivery": tr("bot_status_delivery", user_lang),
            "done": tr("bot_status_done", user_lang),
            "cancelled": tr("bot_status_cancelled", user_lang),
            "restored": tr("bot_status_restored", user_lang),
        }.get(status)
        if not status_text:
            return

        try:
            asyncio.create_task(bot.send_message(user.telegram_id, status_text))
        except Exception:
            logger.opt(exception=True).info("Failed to notify user about order status")

    @staticmethod
    def notify_status_subscribers(order_id: int, status: str) -> None:
        """Push an SSE status update to active order-detail subscribers."""
        try:
            from app.web.app import notify_order_status
            asyncio.create_task(notify_order_status(order_id, status))
        except Exception:
            pass

    @staticmethod
    async def cancel_expired_online_orders(
        session: AsyncSession,
        user_id: Optional[int] = None,
    ) -> List[int]:
        cutoff = OrderService._online_payment_timeout_cutoff()
        stmt = select(Order.id).where(
            Order.status == "new",
            Order.payment_method.in_(OrderService.ONLINE_PAYMENT_METHODS),
            Order.created_at < cutoff,
        )
        if user_id is not None:
            stmt = stmt.where(Order.user_id == user_id)
        order_ids = (await session.execute(stmt)).scalars().all()

        for order_id in order_ids:
            await OrderService.cancel_order(session, order_id, commit=False)

        if order_ids:
            await session.commit()

        return order_ids

    @staticmethod
    async def cancel_expired_online_order(
        session: AsyncSession,
        order: Order,
        commit: bool = True,
    ) -> bool:
        if (
            order.status == "new"
            and order.payment_method in OrderService.ONLINE_PAYMENT_METHODS
            and order.created_at < OrderService._online_payment_timeout_cutoff()
        ):
            await OrderService.cancel_order(session, order.id, commit=False)
            if commit:
                await session.commit()
            return True
        return False

    @staticmethod
    async def create_order(
        user: User,
        order_data: OrderCreateSchema,
        session: AsyncSession,
        *,
        payment_receipt_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        lang = user.language or "ru"
        if not (user.phone or "").strip():
            raise HTTPException(status_code=400, detail=tr("fill_phone_first", lang))

        phone_value = (order_data.phone or "").strip()
        if not phone_value:
            raise HTTPException(status_code=400, detail=tr("enter_phone", lang))
        if len(phone_value) < 9:
            raise HTTPException(status_code=400, detail=tr("invalid_phone", lang))
        if order_data.payment_method == "card_transfer" and not payment_receipt_path:
            raise HTTPException(status_code=400, detail=tr("payment_receipt_required", lang))

        # 0. Check Debt
        if user.debt and user.debt > 0:
            raise HTTPException(status_code=403, detail=tr("has_debt", lang))

        await OrderService.cancel_expired_online_orders(session, user_id=user.id)

        # Auto-cancel existing unpaid online orders but keep the cart intact so
        # users can switch from Click to Payme (or back) without rebuilding it.
        await OrderService.cancel_pending_online_orders(
            session,
            user.id,
            commit=False,
            remove_cart_items=False,
        )

        pickup_enabled = await get_pickup_enabled(session)
        pickup_address = await get_pickup_address(session)
        delivery_options = await get_delivery_options(session, active_only=True)
        delivery_option_id = None
        delivery_option_name = None
        delivery_price = 0
        delivery_latitude = None
        delivery_longitude = None

        # Address and delivery option handling
        if order_data.delivery_method == "pickup":
            if not pickup_enabled:
                raise HTTPException(status_code=400, detail=tr("pickup_unavailable", lang))
            final_address = pickup_address
        else:
            if not order_data.address:
                raise HTTPException(status_code=400, detail=tr("address_required", lang))
            delivery_option = find_delivery_option(delivery_options, order_data.delivery_option_id)
            if not delivery_option:
                raise HTTPException(status_code=400, detail=tr("delivery_option_required", lang))
            delivery_option_id = delivery_option["id"]
            delivery_option_name = delivery_option.get("name_ru") or delivery_option["id"]
            delivery_price = int(delivery_option.get("price") or 0)
            final_address = order_data.address
            if (
                order_data.delivery_location_source == "browser_geolocation"
                and order_data.delivery_latitude is not None
                and order_data.delivery_longitude is not None
            ):
                delivery_latitude = float(order_data.delivery_latitude)
                delivery_longitude = float(order_data.delivery_longitude)
            # Update/Save address if new
            if order_data.address:
                stmt = select(UserAddress).where(
                    UserAddress.user_id == user.id,
                    UserAddress.address_text == order_data.address,
                )
                if not (await session.execute(stmt)).scalar_one_or_none():
                    session.add(UserAddress(user_id=user.id, address_text=order_data.address))

        # 1. Get Cart Items & IDOR Check
        cart_repo = CartRepository(session)
        # Fetch only items belonging to this user
        cart_items = await cart_repo.get_items_by_ids(order_data.item_ids, user.id)
        
        # IDOR Check: Ensure all requested items were found and belong to the user
        if len(cart_items) != len(order_data.item_ids):
            # If lengths differ, it means some IDs were not found for this user
            raise HTTPException(status_code=400, detail=tr("invalid_cart_items", lang))

        if not cart_items:
            raise HTTPException(status_code=400, detail=tr("cart_empty_order", lang))

        items_to_delete = []
        for item in cart_items:
            if not item.product:
                items_to_delete.append(item)

        if items_to_delete:
            for item in items_to_delete:
                await session.delete(item)
            await session.commit()
            raise HTTPException(status_code=400, detail=tr("product_unavailable", lang))

        total_amount = 0
        items_to_process = []

        try:
            # 2. Atomic Stock Update
            for item in cart_items:
                stock_before_order = item.product.stock
                # Проверяем, не снят ли товар с продажи (Soft Delete)
                if not item.product.is_active:
                    raise HTTPException(status_code=400, detail=tr("product_delisted", lang))
                min_order_quantity = get_min_order_quantity_for_product(item.product)
                if item.quantity < min_order_quantity:
                    raise HTTPException(
                        status_code=400,
                        detail=tr("min_product_quantity", lang).replace("{quantity}", str(min_order_quantity)),
                    )
                
                # Atomic update: decrement stock only if stock >= quantity
                stmt = (
                    update(Product)
                    .where(Product.id == item.product_id, Product.stock >= item.quantity)
                    .values(stock=Product.stock - item.quantity)
                    .execution_options(synchronize_session="fetch")
                )
                result = await session.execute(stmt)
                
                if result.rowcount == 0:
                    # Failed to update means out of stock or product missing
                    # We should check which one for better error message, but generally it's stock
                    # For better UX, we could fetch the product to see actual name, but let's fail fast first
                    # Or we can do a check before, but race condition might happen in between.
                    # The atomic update guarantees consistency.
                    
                    # Let's fetch the product name to show a nice error
                    prod = await session.get(Product, item.product_id)
                    name = prod.name_ru if prod else f"ID {item.product_id}"
                    stock = prod.stock if prod else 0
                    raise HTTPException(status_code=400, detail=tr("not_enough_stock", lang))
                
                # If successful, calculate price using the product attached to cart item
                # CAUTION: The product attached to cart_item might be stale in session if not refreshed,
                # but usually it's fine. Safer to use current price. 
                # Since we just updated it, we can trust the price from the 'product' relation loaded in 'cart_items'
                # provided 'cart_repo.get_items_by_ids' loaded valid products.
                
                # However, 'update' doesn't return the price. The 'item.product' is loaded.
                unit_price = item.product.effective_price
                total_amount += unit_price * item.quantity
                items_to_process.append((item, stock_before_order))

            if total_amount <= 0:
                raise HTTPException(status_code=400, detail=tr("order_amount_zero", lang))
            if total_amount < settings.MIN_ORDER_AMOUNT:
                raise HTTPException(
                    status_code=400,
                    detail=tr("min_order_amount", lang).replace("{amount}", str(settings.MIN_ORDER_AMOUNT)),
                )

            # 2.5 Apply Promo Code
            promo_code_id = None
            discount_amount = 0
            promo_code_str = getattr(order_data, "promo_code", None)
            if promo_code_str:
                from app.database.models import PromoCode
                promo_stmt = (
                    select(PromoCode)
                    .where(
                        PromoCode.code == promo_code_str.strip().upper(),
                        PromoCode.is_active == True,
                    )
                    .with_for_update()
                )
                promo = (await session.execute(promo_stmt)).scalar_one_or_none()
                if not promo:
                    raise HTTPException(status_code=400, detail=tr("promo_not_found", lang))
                now = datetime.utcnow()
                if promo.expires_at and promo.expires_at < now:
                    raise HTTPException(status_code=400, detail=tr("promo_expired", lang))
                if promo.usage_limit and promo.used_count >= promo.usage_limit:
                    raise HTTPException(status_code=400, detail=tr("promo_exhausted", lang))
                # Per-user usage check: one promo per user
                from app.database.models import UserPromoUsage
                existing_usage = (await session.execute(
                    select(UserPromoUsage).where(
                        UserPromoUsage.user_id == user.id,
                        UserPromoUsage.promo_id == promo.id,
                    )
                )).scalar_one_or_none()
                if existing_usage:
                    raise HTTPException(status_code=400, detail=tr("promo_already_used", lang))
                if total_amount < promo.min_order_amount:
                    raise HTTPException(
                        status_code=400,
                        detail=tr("promo_min_order", lang).replace("{amount}", f"{promo.min_order_amount:,}"),
                    )
                if promo.discount_type == "percent":
                    discount_amount = int(total_amount * promo.discount_value / 100)
                    if promo.max_discount and discount_amount > promo.max_discount:
                        discount_amount = promo.max_discount
                else:
                    discount_amount = promo.discount_value
                max_allowed_discount = total_amount - settings.MIN_ORDER_AMOUNT
                discount_amount = min(discount_amount, total_amount, max(0, max_allowed_discount))
                promo_code_id = promo.id
                promo.used_count += 1
                session.add(UserPromoUsage(user_id=user.id, promo_id=promo.id))
                total_amount -= discount_amount

            order_total_amount = total_amount + delivery_price

            # 3. Create Order
            new_order = Order(
                user_id=user.id, 
                status="new", 
                payment_method=order_data.payment_method,
                payment_receipt_path=payment_receipt_path,
                delivery_method=order_data.delivery_method, 
                delivery_option_id=delivery_option_id,
                delivery_option_name=delivery_option_name,
                delivery_price=delivery_price,
                delivery_address=final_address,
                delivery_latitude=delivery_latitude,
                delivery_longitude=delivery_longitude,
                total_amount=order_total_amount,
                discount_amount=discount_amount,
                promo_code_id=promo_code_id,
                comment=order_data.comment, 
                contact_phone=phone_value
            )
            session.add(new_order)
            await session.flush() # get ID

            should_clear_cart_now = order_data.payment_method not in OrderService.ONLINE_PAYMENT_METHODS

            # 4. Create Order Items & Clear Cart (Conditional)
            for item, stock_before_order in items_to_process:
                # Формируем имя с учётом формата продажи
                p_name = item.product.name_ru
                if item.product.sell_type == "pack" and item.product.pack_quantity:
                    p_name += f" (уп. {item.product.pack_quantity} шт)"
                session.add(OrderItem(
                    order_id=new_order.id, 
                    product_id=item.product.id,
                    product_name=p_name, 
                    price_at_purchase=item.product.effective_price,
                    quantity=item.quantity,
                    stock_before_order=stock_before_order,
                ))
                if should_clear_cart_now:
                    await session.delete(item)
            
            await session.commit()
        except Exception as exc:
            await session.rollback()
            if isinstance(exc, HTTPException):
                raise
            logger.exception("Failed to create order")
            raise HTTPException(status_code=500, detail=tr("order_failed", lang))

        # 5. Notifications
        # Notify admins about new order
        asyncio.create_task(OrderService._notify_admins_new_order(new_order, user, order_total_amount, final_address))

        payme_url = None
        if order_data.payment_method == "card":
            payme_url = generate_payme_link(new_order.id, order_total_amount)
            try:
                msg = tr("bot_order_created_payme", lang).replace("{order_id}", str(new_order.id)).replace("{amount}", f"{order_total_amount:,}")
                if user.telegram_id:
                    asyncio.create_task(
                        bot.send_message(user.telegram_id, msg, parse_mode="HTML")
                    )
            except Exception:
                logger.exception("Failed to send payme notification")
            return {"status": "redirect", "url": payme_url}
        if order_data.payment_method == "click":
            return {"status": "success", "order_id": new_order.id}
        if order_data.payment_method == "card_transfer":
            try:
                msg = tr("bot_order_created_card_transfer", lang).replace("{order_id}", str(new_order.id)).replace("{amount}", f"{order_total_amount:,}")
                if user.telegram_id:
                    asyncio.create_task(
                        bot.send_message(user.telegram_id, msg, parse_mode="HTML")
                    )
            except Exception:
                logger.exception("Failed to send card transfer order notification")
            return {"status": "success", "order_id": new_order.id}
        else:
            try:
                msg = tr("bot_order_created_cash", lang).replace("{order_id}", str(new_order.id)).replace("{amount}", f"{order_total_amount:,}").replace("{address}", final_address or "")
                if user.telegram_id:
                    asyncio.create_task(
                        bot.send_message(user.telegram_id, msg, parse_mode="HTML")
                    )
            except Exception:
                logger.exception("Failed to send order notification")
            return {"status": "success", "order_id": new_order.id}

    @staticmethod
    async def _notify_admins_new_order(order, user, total_amount, address):
        """Send Telegram notification about new order to all admins/managers."""
        if not settings.NOTIFY_ADMINS_ON_NEW_ORDER:
            return
        try:
            from app.database.core import async_session_maker
            async with async_session_maker() as session:
                stmt = select(User).where(User.role.in_(["superadmin", "manager"]), User.telegram_id.isnot(None))
                admins = (await session.execute(stmt)).scalars().all()

            items_text = ""
            payment_label = {
                "cash": "Наличные",
                "card": "Payme",
                "click": "Click",
                "card_transfer": "Перевод на карту",
            }.get(order.payment_method, order.payment_method)
            msg = tr("bot_new_order_admin", "ru").replace(
                "{order_id}", str(order.id)
            ).replace(
                "{username}", user.username or "—"
            ).replace(
                "{phone}", user.phone or "—"
            ).replace(
                "{amount}", f"{total_amount:,}"
            ).replace(
                "{payment}", payment_label
            ).replace(
                "{address}", address or "—"
            )
            for admin in admins:
                try:
                    await bot.send_message(admin.telegram_id, msg, parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            logger.exception("Failed to notify admins about new order")

    @staticmethod
    async def cancel_order(
        session: AsyncSession,
        order_id: int,
        commit: bool = True,
        remove_cart_items: bool = True,
    ) -> Optional[Order]:
        """Cancel order and optionally commit the transaction."""
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.user),
            )
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = (await session.execute(stmt)).scalar_one_or_none()

        if not order:
            return None

        if order.status == "cancelled":
            return order

        if order.order_type == "product":
            for item in order.items:
                if item.product_id:
                    new_stock_value = Product.stock + item.quantity
                    await session.execute(
                        update(Product)
                        .where(Product.id == item.product_id)
                        .values(stock=new_stock_value)
                        .execution_options(synchronize_session="fetch")
                    )

        if order.promo_code_id and order.discount_amount and order.discount_amount > 0:
            await session.execute(
                update(PromoCode)
                .where(PromoCode.id == order.promo_code_id, PromoCode.used_count > 0)
                .values(used_count=PromoCode.used_count - 1)
                .execution_options(synchronize_session="fetch")
            )
            await session.execute(
                delete(UserPromoUsage)
                .where(UserPromoUsage.user_id == order.user_id, UserPromoUsage.promo_id == order.promo_code_id)
            )

        if remove_cart_items:
            await OrderService.remove_order_items_from_cart(session, order)

        order.status = "cancelled"
        order.admin_unread = False
        if commit:
            await session.commit()
        return order

    @staticmethod
    async def restore_cancelled_cash_order(
        session: AsyncSession,
        order_id: int,
        *,
        commit: bool = True,
    ) -> Optional[Order]:
        """Restore a cancelled cash product order while reserving stock again.

        Cancelling an order returns products to stock and releases its promo
        usage. Restoring it must reverse both operations atomically; changing
        only the status could otherwise oversell products or allow a promo to
        be used twice.
        """
        stmt = (
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.user),
            )
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = (await session.execute(stmt)).scalar_one_or_none()
        if not order:
            return None

        if order.status != "cancelled":
            raise OrderRestoreError("Восстановить можно только отменённый заказ.")
        if order.payment_method != "cash" or order.order_type != "product":
            raise OrderRestoreError("Восстановить можно только товарный заказ с оплатой наличными.")
        if not order.items:
            raise OrderRestoreError("В заказе нет товаров для восстановления.")

        quantities_by_product: dict[int, int] = {}
        for item in order.items:
            if item.product_id is None:
                raise OrderRestoreError("Один из товаров заказа больше недоступен.")
            quantities_by_product[item.product_id] = quantities_by_product.get(item.product_id, 0) + item.quantity

        products = (
            await session.execute(
                select(Product)
                .where(Product.id.in_(quantities_by_product))
                .order_by(Product.id)
                .with_for_update()
            )
        ).scalars().all()
        products_by_id = {product.id: product for product in products}

        # Validate every item before changing any stock value.
        for product_id, quantity in quantities_by_product.items():
            product = products_by_id.get(product_id)
            if not product or not product.is_active:
                raise OrderRestoreError("Один из товаров заказа больше недоступен.")
            if product.stock < quantity:
                raise OrderRestoreError(
                    f"Недостаточно товара «{product.name_ru}» для восстановления заказа."
                )

        promo = None
        if order.promo_code_id and order.discount_amount and order.discount_amount > 0:
            promo = (
                await session.execute(
                    select(PromoCode)
                    .where(PromoCode.id == order.promo_code_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not promo:
                raise OrderRestoreError("Промокод этого заказа больше недоступен для восстановления.")

            if order.user_id:
                promo_usage = (
                    await session.execute(
                        select(UserPromoUsage).where(
                            UserPromoUsage.user_id == order.user_id,
                            UserPromoUsage.promo_id == promo.id,
                        )
                    )
                ).scalar_one_or_none()
                if promo_usage:
                    raise OrderRestoreError(
                        "Промокод уже использован повторно, поэтому заказ нельзя восстановить."
                    )

        for product_id, quantity in quantities_by_product.items():
            products_by_id[product_id].stock -= quantity

        if promo:
            promo.used_count += 1
            if order.user_id:
                session.add(UserPromoUsage(user_id=order.user_id, promo_id=promo.id))

        order.status = "new"
        # Mark the restored order as new for other administrators as well.
        order.admin_unread = True
        if commit:
            await session.commit()
        return order
