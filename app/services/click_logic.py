import hashlib
import hmac
import time
import aiohttp
import asyncio
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.models import Order, ClickTransaction, User, CartItem, OrderItem
from app.config import settings
from app.bot.loader import bot
from app.services.order_service import OrderService
from app.utils.logger import logger
from app.utils.i18n import tr

class ClickErrors:
    SUCCESS = 0
    SIGN_CHECK_FAILED = -1
    INCORRECT_AMOUNT = -2
    ACTION_NOT_FOUND = -3
    ALREADY_PAID = -4
    USER_DOES_NOT_EXIST = -5
    TRANSACTION_DOES_NOT_EXIST = -6
    FAILED_TO_UPDATE_USER = -7
    ERROR_IN_REQUEST = -8
    TRANSACTION_CANCELLED = -9

class ClickService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _parse_amount(raw_amount):
        if raw_amount is None:
            raise ValueError("Amount is missing")
        normalized = "".join(str(raw_amount).split()).replace(",", ".")
        amount = Decimal(normalized)
        if amount != amount.to_integral_value():
            raise ValueError("Amount must be integer")
        return amount

    def check_sign(self, **kwargs):
        """Проверка цифровой подписи (MD5)"""
        click_trans_id = kwargs.get('click_trans_id')
        service_id = kwargs.get('service_id')
        merchant_trans_id = kwargs.get('merchant_trans_id')
        merchant_prepare_id = kwargs.get('merchant_prepare_id', '')
        amount = kwargs.get('amount')
        action = kwargs.get('action')
        sign_time = kwargs.get('sign_time')
        sign_string = kwargs.get('sign_string')

        secret_key = settings.CLICK_SECRET_KEY
        
        # Формула из документации:
        # md5( click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time )
        # Для Complete (action=1) добавляется merchant_prepare_id.
        if str(action) == "1":
            text = (
                f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}"
                f"{merchant_prepare_id}{amount}{action}{sign_time}"
            )
        else:
            text = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{amount}{action}{sign_time}"
        my_sign = hashlib.md5(text.encode('utf-8')).hexdigest()

        return hmac.compare_digest(my_sign, sign_string)

    @staticmethod
    def _validate_service_data(data: dict):
        service_id = data.get("service_id")
        if service_id is None:
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Missing service_id"}
        if str(service_id) != str(settings.CLICK_SERVICE_ID):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Invalid service_id"}

        merchant_id = data.get("merchant_id")
        if merchant_id is not None and str(merchant_id) != str(settings.CLICK_MERCHANT_ID):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Invalid merchant_id"}

        return None

    async def prepare(self, data: dict):
        """Этап 1: Проверка возможности оплаты (Action = 0)"""
        merchant_trans_id = data.get('merchant_trans_id')
        try:
            amount = self._parse_amount(data.get('amount'))
        except (TypeError, ValueError, ArithmeticError):
            return {"error": ClickErrors.INCORRECT_AMOUNT, "error_note": "Incorrect parameter amount"}

        # 1. Проверка action (должен быть 0 для prepare)
        try:
            action = int(data.get('action'))
        except (TypeError, ValueError):
            return {"error": ClickErrors.ACTION_NOT_FOUND, "error_note": "Action not found"}

        if action != 0:
            return {"error": ClickErrors.ACTION_NOT_FOUND, "error_note": "Action not found"}

        service_error = self._validate_service_data(data)
        if service_error:
            return service_error

        # 2. Проверка подписи
        if not self.check_sign(**data):
            return {"error": ClickErrors.SIGN_CHECK_FAILED, "error_note": "SIGN CHECK FAILED!"}

        # 3. Ищем заказ
        try:
            order_id = int(merchant_trans_id)
        except (TypeError, ValueError):
            return {"error": ClickErrors.USER_DOES_NOT_EXIST, "error_note": "User does not exist"}

        stmt = select(Order).where(Order.id == order_id)
        order = (await self.session.execute(stmt)).scalar_one_or_none()

        if not order:
            return {"error": ClickErrors.USER_DOES_NOT_EXIST, "error_note": "User does not exist"}

        if order.payment_method != "click":
            return {
                "error": ClickErrors.USER_DOES_NOT_EXIST,
                "error_note": "User does not exist",
            }

        if await OrderService.cancel_expired_online_order(self.session, order):
            return {"error": ClickErrors.TRANSACTION_CANCELLED, "error_note": "Transaction cancelled"}

        # 4. Проверка суммы
        if int(amount) != int(order.total_amount):
            return {"error": ClickErrors.INCORRECT_AMOUNT, "error_note": "Incorrect parameter amount"}

        # 5. Проверка статуса (если уже оплачен)
        if order.status in ['paid', 'done']:
            return {"error": ClickErrors.ALREADY_PAID, "error_note": "Already paid"}

        if order.status == 'cancelled':
            return {"error": ClickErrors.TRANSACTION_CANCELLED, "error_note": "Transaction cancelled"}

        # 6. Защита от повторного Prepare с уже подтверждённым click_trans_id
        try:
            click_trans_id = int(data.get('click_trans_id'))
        except (TypeError, ValueError):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Error in request from click"}

        existing_tx = (await self.session.execute(
            select(ClickTransaction).where(
                ClickTransaction.click_trans_id == click_trans_id,
                ClickTransaction.status == 'confirmed',
            )
        )).scalar_one_or_none()
        if existing_tx:
            return {"error": ClickErrors.ALREADY_PAID, "error_note": "Already paid"}

        # Всё ок — возвращаем merchant_prepare_id = order_id
        return {
            "click_trans_id": data['click_trans_id'],
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": order_id,
            "error": ClickErrors.SUCCESS,
            "error_note": "Success"
        }

    def _build_fiscal_payload(self, payment_id: int, order: Order):
        if order.order_type == "product" and not order.items:
            logger.error(
                "Click Fiscal Error: order %s has no items for product order",
                order.id,
            )
            return None

        items_list = []
        if order.order_type == "product":
            expected_total = 0
            for item in order.items:
                if item.quantity <= 0 or item.price_at_purchase <= 0:
                    logger.error(
                        "Click Fiscal Error: invalid item data for order %s (item %s)",
                        order.id,
                        item.id,
                    )
                    return None
                expected_total += int(item.price_at_purchase) * int(item.quantity)

            discount = getattr(order, 'discount_amount', 0) or 0
            delivery_price = int(getattr(order, 'delivery_price', 0) or 0)
            if expected_total - discount + delivery_price != int(order.total_amount):
                logger.error(
                    "Click Fiscal Error: order %s items total %s - discount %s + delivery %s does not match order total %s",
                    order.id,
                    expected_total,
                    discount,
                    delivery_price,
                    order.total_amount,
                )
                return None

            distributed = 0
            order_items_list = list(order.items)
            for idx, item in enumerate(order_items_list):
                item_total = int(item.price_at_purchase) * int(item.quantity)
                spic = item.product.ikpu if item.product and item.product.ikpu else "00702001001000000"
                package_code = settings.DEFAULT_PACKAGE_CODE
                if item.product and item.product.package_code is not None:
                    package_code = item.product.package_code

                if discount > 0 and expected_total > 0:
                    if idx == len(order_items_list) - 1:
                        item_discount = discount - distributed
                    else:
                        item_discount = int(discount * item_total / expected_total)
                        distributed += item_discount
                    # Use amount=1 with full line total to avoid tiyin rounding mismatch
                    line_total_tiyins = (item_total - item_discount) * 100
                    items_list.append({
                        "spic": spic,
                        "title": f"{item.product_name} ({item.quantity} шт)",
                        "package_code": str(package_code),
                        "price": max(1, line_total_tiyins),
                        "amount": 1,
                        "units": 241092,
                        "vat_percent": 0,
                    })
                else:
                    items_list.append({
                        "spic": spic,
                        "title": item.product_name,
                        "package_code": str(package_code),
                        "price": int(item.price_at_purchase) * 100,
                        "amount": item.quantity,
                        "units": 241092,
                        "vat_percent": 0,
                    })
            if delivery_price > 0:
                items_list.append({
                    "spic": "00702001001000000",
                    "title": getattr(order, "delivery_option_name", None) or "Доставка",
                    "package_code": str(settings.DEFAULT_PACKAGE_CODE),
                    "price": delivery_price * 100,
                    "amount": 1,
                    "units": 241092,
                    "vat_percent": 0,
                })

        if order.order_type == "debt_repayment":
            items_list.append(
                {
                    "spic": "00702001001000000",
                    "title": "Погашение долга",
                    "package_code": str(settings.DEFAULT_PACKAGE_CODE),
                    "price": int(order.total_amount) * 100,
                    "amount": 1,
                    "units": 241092,
                    "vat_percent": 0,
                }
            )

        payload = {
            "service_id": int(settings.CLICK_SERVICE_ID),
            "payment_id": payment_id,  # ID платежа в системе CLICK (не наш!)
            "items": items_list,
            "received_ecash": int(order.total_amount) * 100,  # Сумма электронными (текущая оплата)
            "received_cash": 0,
            "received_card": 0,
        }

        return payload

    async def send_fiscal_data(self, payload: dict, order_id: int):
        """
        Отправка фискальных данных в Click (см. файл Фискализация данных.pdf)
        """
        url = "https://api.click.uz/v2/merchant/payment/ofd_data/submit_items"
        timestamp = int(time.time())
        digest = hashlib.sha1(f"{timestamp}{settings.CLICK_SECRET_KEY}".encode("utf-8")).hexdigest()

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Auth": f"{settings.CLICK_MERCHANT_USER_ID}:{digest}:{timestamp}",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as http_session:
                async with http_session.post(url, headers=headers, json=payload) as resp:
                    resp_data = await resp.json()
                    if resp.status != 200:
                        logger.error("Click Fiscal Error (order %s): %s", order_id, resp_data)
                    else:
                        logger.info("Click Fiscal Success (order %s): %s", order_id, resp_data)
        except Exception as e:
            logger.error("Click Fiscal Request Failed (order %s): %s", order_id, e)

    async def complete(self, data: dict):
        """Этап 2: Проведение оплаты (Action = 1)"""
        merchant_trans_id = data.get('merchant_trans_id')
        try:
            amount = self._parse_amount(data.get('amount'))
        except (TypeError, ValueError, ArithmeticError):
            return {"error": ClickErrors.INCORRECT_AMOUNT, "error_note": "Incorrect parameter amount"}
        try:
            click_trans_id = int(data.get('click_trans_id'))
        except (TypeError, ValueError):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Error in request from click"}

        try:
            click_paydoc_id = int(data.get('click_paydoc_id'))
        except (TypeError, ValueError):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Error in request from click"}

        # 1. Проверка action (должен быть 1 для complete)
        try:
            action = int(data.get('action'))
        except (TypeError, ValueError):
            return {"error": ClickErrors.ACTION_NOT_FOUND, "error_note": "Action not found"}

        if action != 1:
            return {"error": ClickErrors.ACTION_NOT_FOUND, "error_note": "Action not found"}

        service_error = self._validate_service_data(data)
        if service_error:
            return service_error

        # 2. Проверка подписи
        if not self.check_sign(**data):
            return {"error": ClickErrors.SIGN_CHECK_FAILED, "error_note": "SIGN CHECK FAILED!"}

        # 3. Проверка merchant_prepare_id (должен совпадать с merchant_trans_id = order_id)
        merchant_prepare_id = data.get('merchant_prepare_id', '')
        try:
            order_id = int(merchant_trans_id)
        except (TypeError, ValueError):
            return {"error": ClickErrors.USER_DOES_NOT_EXIST, "error_note": "User does not exist"}

        if not merchant_prepare_id:
            return {"error": ClickErrors.TRANSACTION_DOES_NOT_EXIST, "error_note": "Transaction does not exist"}
        try:
            prepare_id = int(merchant_prepare_id)
        except (TypeError, ValueError):
            return {"error": ClickErrors.TRANSACTION_DOES_NOT_EXIST, "error_note": "Transaction does not exist"}
        if prepare_id != order_id:
            return {"error": ClickErrors.TRANSACTION_DOES_NOT_EXIST, "error_note": "Transaction does not exist"}

        # 4. Ищем заказ
        stmt = (
            select(Order)
            .options(
                selectinload(Order.user),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = (await self.session.execute(stmt)).scalar_one_or_none()

        if not order:
            return {"error": ClickErrors.USER_DOES_NOT_EXIST, "error_note": "User does not exist"}

        if order.payment_method != "click":
            return {
                "error": ClickErrors.USER_DOES_NOT_EXIST,
                "error_note": "User does not exist",
            }

        if await OrderService.cancel_expired_online_order(self.session, order, commit=False):
            await self.session.commit()
            return {"error": ClickErrors.TRANSACTION_CANCELLED, "error_note": "Transaction cancelled"}

        # 5. Проверка на отмену (если error < 0, Click отменяет платёж)
        # По документации: поставщик должен снять бронь и вернуть error = -9
        raw_error = data.get('error', 0)
        if raw_error in (None, ""):
            raw_error = 0
        try:
            error_code = int(raw_error)
        except (TypeError, ValueError):
            return {"error": ClickErrors.ERROR_IN_REQUEST, "error_note": "Error in request from click"}

        if error_code < 0:
            # Попытка отменить уже подтверждённую/доставляемую/завершённую транзакцию → -4
            if order.status in ("paid", "done", "delivery"):
                return {
                    "click_trans_id": click_trans_id,
                    "merchant_trans_id": merchant_trans_id,
                    "error": ClickErrors.ALREADY_PAID,
                    "error_note": "Already paid",
                }

            # Попытка отменить уже отменённую транзакцию → -9
            if order.status == "cancelled":
                return {
                    "click_trans_id": click_trans_id,
                    "merchant_trans_id": merchant_trans_id,
                    "error": ClickErrors.TRANSACTION_CANCELLED,
                    "error_note": "Transaction cancelled",
                }

            # Only cancel the order if it's still new and assigned to click
            if order.status == "new" and order.payment_method == "click":
                await OrderService.cancel_order(self.session, order.id, commit=False)
            await self.session.commit()

            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "error": ClickErrors.TRANSACTION_CANCELLED,
                "error_note": "Transaction cancelled",
            }

        # 6. Идемпотентность (повторный запрос на уже проведённую оплату)
        tx_stmt = select(ClickTransaction).where(
            ClickTransaction.click_trans_id == click_trans_id,
            ClickTransaction.status == 'confirmed',
        )
        existing_tx = (await self.session.execute(tx_stmt)).scalar_one_or_none()

        if existing_tx:
            if order.status == "cancelled":
                return {
                    "click_trans_id": click_trans_id,
                    "merchant_trans_id": merchant_trans_id,
                    "error": ClickErrors.TRANSACTION_CANCELLED,
                    "error_note": "Transaction cancelled",
                }
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": order.id,
                "error": ClickErrors.ALREADY_PAID,
                "error_note": "Already paid",
            }

        if order.status in ("paid", "done"):
            return {"error": ClickErrors.ALREADY_PAID, "error_note": "Already paid"}

        if order.status == "cancelled":
            return {"error": ClickErrors.TRANSACTION_CANCELLED, "error_note": "Transaction cancelled"}

        # 7. Проводим оплату
        if int(amount) != int(order.total_amount):
            return {"error": ClickErrors.INCORRECT_AMOUNT, "error_note": "Incorrect parameter amount"}

        user_locked = None
        if order.order_type == 'debt_repayment':
            user_stmt = select(User).where(User.id == order.user_id).with_for_update()
            user_locked = (await self.session.execute(user_stmt)).scalar_one_or_none()

        if order.status == 'new':
            order.status = 'paid'
            order.payment_method = 'click'

            # SSE: notify subscribers about status change
            try:
                from app.web.app import notify_order_status
                asyncio.create_task(notify_order_status(order.id, "paid"))
            except Exception:
                pass

            # Погашение долга
            if order.order_type == 'debt_repayment':
                order.status = 'done'

                # SSE: notify subscribers about status change
                try:
                    from app.web.app import notify_order_status
                    asyncio.create_task(notify_order_status(order.id, "done"))
                except Exception:
                    pass

                if user_locked:
                    if user_locked.debt < order.total_amount:
                        user_locked.debt = 0 # Безопасное списание
                    else:
                        user_locked.debt -= order.total_amount
            else:
                await OrderService.remove_order_items_from_cart(self.session, order)

            # Записываем транзакцию
            new_tx = ClickTransaction(
                click_trans_id=click_trans_id,
                service_id=int(data.get('service_id')),
                click_paydoc_id=click_paydoc_id,
                merchant_trans_id=merchant_trans_id,
                amount=amount,
                action=1,
                error=0,
                sign_time=data.get('sign_time'),
                sign_string=data.get('sign_string'),
                status='confirmed'
            )
            self.session.add(new_tx)
            await self.session.commit()

            # Отправляем чек в налоговую через Click
            # click_paydoc_id - это номер платежа в системе Click (payment_id для фискализации)
            try:
                fiscal_payload = self._build_fiscal_payload(click_paydoc_id, order)
                if fiscal_payload:
                    # Запускаем в фоне, чтобы не тормозить ответ
                    asyncio.create_task(self.send_fiscal_data(fiscal_payload, order.id))
            except Exception as e:
                logger.error(f"Failed to start fiscal task: {e}")

            # Уведомление
            try:
                user_lang = order.user.language if order.user else "ru"
                msg = tr("bot_paid_click", user_lang).replace("{order_id}", str(order.id)).replace("{amount}", f"{order.total_amount:,}")
                if order.user and order.user.telegram_id:
                    asyncio.create_task(bot.send_message(order.user.telegram_id, msg, parse_mode="HTML"))
            except Exception:
                logger.exception("Failed to send Click payment notification")

        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": order.id,
            "error": ClickErrors.SUCCESS,
            "error_note": "Success"
        }
