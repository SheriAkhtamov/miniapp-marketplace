import asyncio
import time
from datetime import datetime, timedelta
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError
from app.database.models import Order, PaymeTransaction, User, Product, OrderItem
from app.config import settings
from app.bot.loader import bot
from app.services.order_service import OrderService
from app.utils.money import normalize_amount
from app.utils.logger import logger
from app.utils.i18n import tr

class PaymeErrors:
    INSUFFICIENT_PRIVILEGE = -32504
    JSON_PARSE_ERROR = -32700
    METHOD_NOT_FOUND = -32601
    INVALID_AMOUNT = -31001
    TRANSACTION_NOT_FOUND = -31003
    ORDER_NOT_FOUND = -31050
    ORDER_AVAILABLE = -31051
    CANT_CANCEL = -31007
    ALREADY_DONE = -31008

class PaymeException(Exception):
    def __init__(self, code: int, message: dict | str = "Error", data: str = None):
        self.code = code
        self.message = message
        self.data = data

class PaymeService:
    LOCK_TIMEOUT_MS = 5000  # 5 seconds in milliseconds
    DEFAULT_TIMEOUT_MINUTES = 720

    def _transaction_timeout_minutes(self) -> int:
        return getattr(settings, "ORDER_PAYMENT_TIMEOUT_MINUTES", self.DEFAULT_TIMEOUT_MINUTES)

    def _transaction_timeout_ms(self) -> int:
        return self._transaction_timeout_minutes() * 60 * 1000

    def _transaction_timeout_seconds(self) -> int:
        return self._transaction_timeout_minutes() * 60

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _set_lock_timeout(self) -> None:
        # NOTE: PostgreSQL SET does not support parameterized values via
        # asyncpg's extended query protocol, so we use a literal here.
        # The value is normalized to int before interpolation.
        timeout_ms = int(self.LOCK_TIMEOUT_MS)
        await self.session.execute(
            text(f"SET LOCAL lock_timeout = '{timeout_ms}'")
        )

    def _is_lock_error(self, error: OperationalError) -> bool:
        orig = getattr(error, "orig", None)
        if orig and orig.__class__.__name__ == "LockNotAvailable":
            return True
        message = str(error).lower()
        return "lock timeout" in message or "lock not available" in message or "could not obtain lock" in message

    async def _raise_lock_error(self) -> None:
        await self.session.rollback()
        raise PaymeException(PaymeErrors.ORDER_AVAILABLE, {
            "ru": "Заказ занят, попробуйте позже",
            "uz": "Buyurtma band, keyinroq urinib ko'ring",
            "en": "Order is busy, try again later",
        })

    async def check_perform_transaction(self, amount_tiyins: int, account: dict):
        try:
            amount_tiyins = normalize_amount(amount_tiyins)
        except ValueError:
            raise PaymeException(PaymeErrors.INVALID_AMOUNT, {
                "ru": "Неверная сумма",
                "uz": "Noto'g'ri summa",
                "en": "Invalid amount",
            })
        order_id = account.get(settings.PAYME_ACCOUNT_FIELD)

        try:
            order_id = int(str(order_id).strip().lstrip("#"))
        except (ValueError, TypeError):
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Неверный ID заказа", "uz": "Buyurtma ID noto'g'ri", "en": "Invalid order ID"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        stmt = (
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
            .where(Order.id == order_id)
        )
        order = (await self.session.execute(stmt)).scalar_one_or_none()

        if not order:
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.order_type == "debt_repayment" and order.payment_method != "card":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не доступен для оплаты", "uz": "Buyurtma to'lov uchun mavjud emas", "en": "Order not available for payment"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.payment_method != "card":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не доступен для оплаты через Payme", "uz": "Buyurtma Payme orqali to'lov uchun mavjud emas", "en": "Order not available for Payme payment"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if await OrderService.cancel_expired_online_order(self.session, order):
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ просрочен и отменен", "uz": "Buyurtma muddati o'tgan va bekor qilingan", "en": "Order expired and cancelled"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.total_amount * 100 != amount_tiyins:
            raise PaymeException(PaymeErrors.INVALID_AMOUNT, {
                "ru": "Неверная сумма",
                "uz": "Noto'g'ri summa",
                "en": "Invalid amount",
            })

        if order.status != "new":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ уже оплачен или отменен", "uz": "Buyurtma allaqachon to'langan yoki bekor qilingan", "en": "Order already paid or cancelled"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        result = {"allow": True}

        # Build detail (fiscalization) per Payme docs — detail goes in CheckPerformTransaction
        result["detail"] = self._build_receipt_detail(order)

        return result

    def _build_receipt_detail(self, order: Order) -> dict:
        """Build fiscal receipt detail object for Payme."""
        if order.order_type == "debt_repayment" and not order.items:
            receipt_items = [
                {
                    "title": "Погашение долга",
                    "price": order.total_amount * 100,
                    "count": 1,
                    "code": "00702001001000000",
                    "units": 241092,
                    "vat_percent": 0,
                    "package_code": settings.DEFAULT_PACKAGE_CODE,
                }
            ]
        else:
            discount = getattr(order, 'discount_amount', 0) or 0
            delivery_price = getattr(order, 'delivery_price', 0) or 0
            items_raw_total = sum(i.price_at_purchase * i.quantity for i in order.items)

            receipt_items = []
            distributed = 0
            items_list = list(order.items)
            for idx, item in enumerate(items_list):
                item_total = item.price_at_purchase * item.quantity
                ikpu = item.product.ikpu if item.product and item.product.ikpu else "00702001001000000"
                pkg = item.product.package_code if item.product and item.product.package_code else settings.DEFAULT_PACKAGE_CODE

                if discount > 0 and items_raw_total > 0:
                    if idx == len(items_list) - 1:
                        item_discount = discount - distributed
                    else:
                        item_discount = int(discount * item_total / items_raw_total)
                        distributed += item_discount
                    # Use count=1 with full line total to avoid tiyin rounding mismatch
                    line_total_tiyins = (item_total - item_discount) * 100
                    receipt_items.append({
                        "title": f"{item.product_name} ({item.quantity} шт)",
                        "price": max(1, line_total_tiyins),
                        "count": 1,
                        "code": ikpu,
                        "units": 241092,
                        "vat_percent": 0,
                        "package_code": pkg,
                    })
                else:
                    receipt_items.append({
                        "title": item.product_name,
                        "price": item.price_at_purchase * 100,
                        "count": item.quantity,
                        "code": ikpu,
                        "units": 241092,
                        "vat_percent": 0,
                        "package_code": pkg,
                    })
            if delivery_price > 0:
                receipt_items.append({
                    "title": getattr(order, "delivery_option_name", None) or "Доставка",
                    "price": delivery_price * 100,
                    "count": 1,
                    "code": "00702001001000000",
                    "units": 241092,
                    "vat_percent": 0,
                    "package_code": settings.DEFAULT_PACKAGE_CODE,
                })

        return {"receipt_type": 0, "items": receipt_items}

    async def create_transaction(self, payme_id: str, time_ms: int, amount_tiyins: int, account: dict):
        try:
            amount_tiyins = normalize_amount(amount_tiyins)
        except ValueError:
            raise PaymeException(PaymeErrors.INVALID_AMOUNT, {
                "ru": "Неверная сумма",
                "uz": "Noto'g'ri summa",
                "en": "Invalid amount",
            })
        order_id = account.get(settings.PAYME_ACCOUNT_FIELD)

        # --- Idempotency: check if this exact payme_id already exists ---
        stmt_tx = select(PaymeTransaction).where(PaymeTransaction.payme_id == payme_id)
        transaction = (await self.session.execute(stmt_tx)).scalar_one_or_none()

        if transaction:
            if transaction.state == 1:
                # Check timeout: 12 hours from Payme creation time
                if int(time.time() * 1000) - transaction.time > self._transaction_timeout_ms():
                    transaction.state = -1
                    transaction.reason = 4
                    transaction.cancel_time = datetime.utcnow()
                    await OrderService.cancel_order(self.session, transaction.order_id, commit=False)
                    await self.session.commit()
                    raise PaymeException(PaymeErrors.ALREADY_DONE, {
                        "ru": "Транзакция отменена по таймауту",
                        "uz": "Tranzaksiya vaqt tugashi sababli bekor qilindi",
                        "en": "Transaction cancelled due to timeout",
                    })
                # Same tx, still active — return idempotent response
                return {
                    "create_time": int(transaction.create_time.timestamp() * 1000),
                    "transaction": str(transaction.id),
                    "state": 1,
                }
            else:
                # Transaction exists but already completed/cancelled — return current state
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Невозможно выполнить операцию",
                    "uz": "Operatsiyani bajarib bo'lmaydi",
                    "en": "Unable to perform operation",
                })

        # --- New transaction: validate order ---
        try:
            order_id = int(str(order_id).strip().lstrip("#"))
        except (ValueError, TypeError):
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Неверный ID заказа", "uz": "Buyurtma ID noto'g'ri", "en": "Invalid order ID"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        try:
            await self._set_lock_timeout()
            stmt_order = (
                select(Order)
                .options(
                    selectinload(Order.user),
                    selectinload(Order.items),
                    selectinload(Order.items).selectinload(OrderItem.product),
                )
                .where(Order.id == order_id)
                .with_for_update()
            )
            order = (await self.session.execute(stmt_order)).scalar_one_or_none()
        except OperationalError as error:
            if self._is_lock_error(error):
                await self._raise_lock_error()
            raise

        if not order:
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.order_type == "debt_repayment" and order.payment_method != "card":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не доступен для оплаты", "uz": "Buyurtma to'lov uchun mavjud emas", "en": "Order not available for payment"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.payment_method != "card":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ не доступен для оплаты через Payme", "uz": "Buyurtma Payme orqali to'lov uchun mavjud emas", "en": "Order not available for Payme payment"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if await OrderService.cancel_expired_online_order(self.session, order, commit=False):
            await self.session.commit()
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ просрочен и отменен", "uz": "Buyurtma muddati o'tgan va bekor qilingan", "en": "Order expired and cancelled"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.total_amount * 100 != amount_tiyins:
            raise PaymeException(PaymeErrors.INVALID_AMOUNT, {
                "ru": "Неверная сумма",
                "uz": "Noto'g'ri summa",
                "en": "Invalid amount",
            })

        if order.status != "new":
            raise PaymeException(
                PaymeErrors.ORDER_NOT_FOUND,
                {"ru": "Заказ уже оплачен или отменен", "uz": "Buyurtma allaqachon to'langan yoki bekor qilingan", "en": "Order already paid or cancelled"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        if order.order_type == "debt_repayment":
            if order.user and order.user.debt is not None:
                debt_in_tiyins = order.user.debt * 100
                if amount_tiyins > debt_in_tiyins:
                    await OrderService.cancel_order(self.session, order.id, commit=False)
                    await self.session.commit()
                    raise PaymeException(PaymeErrors.INVALID_AMOUNT, {
                        "ru": "Сумма превышает текущий долг",
                        "uz": "Summa joriy qarzdan oshib ketdi",
                        "en": "Amount exceeds current debt",
                    })
        elif order.order_type == "product":
            if not order.items:
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Заказ не готов",
                    "uz": "Buyurtma tayyor emas",
                    "en": "Order not ready",
                })

        # If another ACTIVE transaction (state=1) already exists for this order,
        # reject with -31051 (ORDER_AVAILABLE) per Payme spec (-31050...-31099 range).
        stmt_check = select(PaymeTransaction).where(
            PaymeTransaction.order_id == order_id,
            PaymeTransaction.state == 1,
        )
        existing_active = (await self.session.execute(stmt_check)).scalar_one_or_none()
        if existing_active:
            raise PaymeException(
                PaymeErrors.ORDER_AVAILABLE,
                {"ru": "Другая транзакция обрабатывает этот заказ", "uz": "Boshqa tranzaksiya bu buyurtmani qayta ishlamoqda", "en": "Another transaction is processing this order"},
                data=settings.PAYME_ACCOUNT_FIELD,
            )

        new_tx = PaymeTransaction(
            payme_id=payme_id,
            time=time_ms,
            amount=amount_tiyins,
            order_id=order_id,
            state=1,
        )
        new_tx.order = order
        self.session.add(new_tx)
        await self.session.commit()

        return {
            "create_time": int(new_tx.create_time.timestamp() * 1000),
            "transaction": str(new_tx.id),
            "state": 1,
        }

    async def perform_transaction(self, payme_id: str):
        try:
            await self._set_lock_timeout()
            stmt = (
                select(PaymeTransaction)
                .where(PaymeTransaction.payme_id == payme_id)
                .with_for_update()
            )
            transaction = (await self.session.execute(stmt)).scalar_one_or_none()
        except OperationalError as error:
            if self._is_lock_error(error):
                await self._raise_lock_error()
            raise
        
        if not transaction:
            raise PaymeException(PaymeErrors.TRANSACTION_NOT_FOUND, {
                "ru": "Транзакция не найдена",
                "uz": "Tranzaksiya topilmadi",
                "en": "Transaction not found",
            })

        if transaction.state == 1:
            # Check timeout: 12h (43,200,000 ms) from Payme creation time
            if int(time.time() * 1000) - transaction.time > self._transaction_timeout_ms():
                transaction.state = -1
                transaction.reason = 4
                transaction.cancel_time = datetime.utcnow()
                await OrderService.cancel_order(self.session, transaction.order_id, commit=False)
                await self.session.commit()
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Транзакция отменена по таймауту",
                    "uz": "Tranzaksiya vaqt tugashi sababli bekor qilindi",
                    "en": "Transaction cancelled due to timeout",
                })

            try:
                await self._set_lock_timeout()
                stmt_order = (
                    select(Order)
                    .options(
                        selectinload(Order.user),
                        selectinload(Order.items),
                        selectinload(Order.items).selectinload(OrderItem.product),
                    )
                    .where(Order.id == transaction.order_id)
                    .with_for_update()
                )
                order = (await self.session.execute(stmt_order)).scalar_one_or_none()
            except OperationalError as error:
                if self._is_lock_error(error):
                    await self._raise_lock_error()
                raise
            
            if not order:
                raise PaymeException(
                    PaymeErrors.ORDER_NOT_FOUND,
                    {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
                    data=settings.PAYME_ACCOUNT_FIELD,
                )

            if order.payment_method != "card":
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Невозможно выполнить операцию",
                    "uz": "Operatsiyani bajarib bo'lmaydi",
                    "en": "Unable to perform operation",
                })

            if await OrderService.cancel_expired_online_order(self.session, order, commit=False):
                await self.session.commit()
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Заказ просрочен и отменен",
                    "uz": "Buyurtma muddati o'tgan va bekor qilingan",
                    "en": "Order expired and cancelled",
                })

            if order.status != "new":
                raise PaymeException(PaymeErrors.ALREADY_DONE, {
                    "ru": "Невозможно выполнить операцию",
                    "uz": "Operatsiyani bajarib bo'lmaydi",
                    "en": "Unable to perform operation",
                })

            transaction.state = 2
            transaction.perform_time = datetime.utcnow()

            user_locked = None
            if order.order_type == "debt_repayment":
                try:
                    await self._set_lock_timeout()
                    stmt_user = select(User).where(User.id == order.user_id).with_for_update()
                    user_locked = (await self.session.execute(stmt_user)).scalar_one_or_none()
                except OperationalError as error:
                    if self._is_lock_error(error):
                        await self._raise_lock_error()
                    raise
            order.status = "paid"
            order.payment_method = "card"

            # SSE: notify subscribers about status change
            try:
                from app.web.app import notify_order_status
                asyncio.create_task(notify_order_status(order.id, "paid"))
            except Exception:
                pass

            # ЛОГИКА ПОГАШЕНИЯ ДОЛГА
            if order.order_type == "debt_repayment":
                order.status = "done"  # Сразу завершен

                # SSE: notify subscribers about status change
                try:
                    from app.web.app import notify_order_status
                    asyncio.create_task(notify_order_status(order.id, "done"))
                except Exception:
                    pass

                paid_amount = order.total_amount

                if user_locked:
                    if user_locked.debt < paid_amount:
                        user_locked.debt = 0
                    else:
                        user_locked.debt -= paid_amount

                # Уведомление
                try:
                    user_lang = order.user.language if order.user else "ru"
                    msg = tr("bot_debt_paid", user_lang).replace("{amount}", f"{paid_amount:,}").replace("{remaining}", f"{user_locked.debt if user_locked else 0:,}")
                    if order.user and order.user.telegram_id:
                        asyncio.create_task(
                            bot.send_message(order.user.telegram_id, msg, parse_mode="HTML")
                        )
                except Exception:
                    logger.exception("Failed to send Payme debt repayment notification")
            else:
                # Уведомление для обычных заказов (оплата товара через Payme)
                try:
                    user_lang = order.user.language if order.user else "ru"
                    msg = tr("bot_paid_payme", user_lang).replace("{order_id}", str(order.id)).replace("{amount}", f"{order.total_amount:,}")
                    if order.user and order.user.telegram_id:
                        asyncio.create_task(
                            bot.send_message(order.user.telegram_id, msg, parse_mode="HTML")
                        )
                except Exception:
                    logger.exception("Failed to send Payme payment notification")

                await OrderService.remove_order_items_from_cart(self.session, order)
            
            await self.session.commit()
            
            return {
                "perform_time": int(transaction.perform_time.timestamp() * 1000),
                "transaction": str(transaction.id),
                "state": 2
            }

        if transaction.state == 2:
            # Idempotency: already performed
            return {
                "perform_time": int(transaction.perform_time.timestamp() * 1000),
                "transaction": str(transaction.id),
                "state": 2,
            }

        # state < 0 — transaction was cancelled, cannot perform
        raise PaymeException(PaymeErrors.ALREADY_DONE, {
            "ru": "Невозможно выполнить операцию",
            "uz": "Operatsiyani bajarib bo'lmaydi",
            "en": "Unable to perform operation",
        })

    async def cancel_transaction(self, payme_id: str, reason: int):
        stmt = select(PaymeTransaction).where(PaymeTransaction.payme_id == payme_id).with_for_update()
        transaction = (await self.session.execute(stmt)).scalar_one_or_none()
        
        if not transaction:
            raise PaymeException(PaymeErrors.TRANSACTION_NOT_FOUND, {
                "ru": "Транзакция не найдена",
                "uz": "Tranzaksiya topilmadi",
                "en": "Transaction not found",
            })

        # Идемпотентность: если уже отменена, возвращаем успех
        if transaction.state < 0:
            return {
                "cancel_time": int(transaction.cancel_time.timestamp() * 1000),
                "transaction": str(transaction.id),
                "state": transaction.state,
            }

        # Отмена подтвержденной транзакции (state 2 → -2)
        # Per docs: Метод CancelTransaction отменяет как созданную, так и проведенную транзакцию.
        # -31007 только если товар/услуга уже предоставлены (заказ выполнен/доставлен)
        if transaction.state == 2:
            stmt_order = select(Order).where(Order.id == transaction.order_id)
            order = (await self.session.execute(stmt_order)).scalar_one_or_none()
            if order and order.status in ("done", "delivery"):
                raise PaymeException(PaymeErrors.CANT_CANCEL, {
                    "ru": "Заказ выполнен или в доставке. Невозможно отменить транзакцию",
                    "uz": "Buyurtma bajarilgan yoki yetkazilmoqda. Tranzaksiyani bekor qilib bo'lmaydi",
                    "en": "Order completed or in delivery. Unable to cancel transaction",
                })
            transaction.state = -2
            transaction.reason = reason
            transaction.cancel_time = datetime.utcnow()
            if order:
                await OrderService.cancel_order(self.session, order.id, commit=False)
            await self.session.commit()
            return {
                "cancel_time": int(transaction.cancel_time.timestamp() * 1000),
                "transaction": str(transaction.id),
                "state": transaction.state,
            }

        # Отмена созданной (не оплаченной) транзакции (state 1 → -1)
        if transaction.state == 1:
            transaction.state = -1
            transaction.reason = reason
            transaction.cancel_time = datetime.utcnow()
            # Only cancel the order if it's still unpaid and assigned to this payment method.
            # The order may have been paid via another method (Click/cash) in the meantime.
            stmt_order = select(Order).where(Order.id == transaction.order_id)
            order = (await self.session.execute(stmt_order)).scalar_one_or_none()
            if order and order.status == "new" and order.payment_method == "card":
                await OrderService.cancel_order(self.session, order.id, commit=False)
            await self.session.commit()

        return {
            "cancel_time": int(transaction.cancel_time.timestamp() * 1000),
            "transaction": str(transaction.id),
            "state": transaction.state,
        }

    async def check_transaction(self, payme_id: str):
        stmt = select(PaymeTransaction).where(PaymeTransaction.payme_id == payme_id)
        transaction = (await self.session.execute(stmt)).scalar_one_or_none()

        if not transaction:
            raise PaymeException(PaymeErrors.TRANSACTION_NOT_FOUND, {
                "ru": "Транзакция не найдена",
                "uz": "Tranzaksiya topilmadi",
                "en": "Transaction not found",
            })

        return {
            "create_time": int(transaction.create_time.timestamp() * 1000) if transaction.create_time else 0,
            "perform_time": int(transaction.perform_time.timestamp() * 1000) if transaction.perform_time else 0,
            "cancel_time": int(transaction.cancel_time.timestamp() * 1000) if transaction.cancel_time else 0,
            "transaction": str(transaction.id),
            "state": transaction.state,
            "reason": transaction.reason
        }

    async def get_statement(self, from_time: int, to_time: int):
        stmt = (
            select(PaymeTransaction)
            .where(
                PaymeTransaction.time >= from_time,
                PaymeTransaction.time <= to_time,
            )
            .order_by(PaymeTransaction.time.asc())
        )
        transactions = (await self.session.execute(stmt)).scalars().all()
        
        return {
            "transactions": [
                {
                    "id": tx.payme_id,
                    "time": tx.time,
                    "amount": tx.amount,
                    "account": {settings.PAYME_ACCOUNT_FIELD: str(tx.order_id)},
                    "create_time": int(tx.create_time.timestamp() * 1000),
                    "perform_time": int(tx.perform_time.timestamp() * 1000) if tx.perform_time else 0,
                    "cancel_time": int(tx.cancel_time.timestamp() * 1000) if tx.cancel_time else 0,
                    "transaction": str(tx.id),
                    "state": tx.state,
                    "reason": tx.reason
                }
                for tx in transactions
            ]
        }
