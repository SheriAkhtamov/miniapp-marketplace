import base64
from urllib.parse import urlencode
from app.config import settings

def generate_payme_link(order_id: int, amount_sum: int) -> str:
    """
    Генерирует ссылку для редиректа на форму оплаты Payme.
    amount_sum: Сумма в сумах (будет переведена в тийины)
    """
    amount_tiyin = amount_sum * 100
    
    # Формируем строку параметров
    # m = Merchant ID
    # ac.order_id = ID заказа (ключ order_id берем из конфига)
    # a = Сумма в тийинах
    params = f"m={settings.PAYME_ID};ac.{settings.PAYME_ACCOUNT_FIELD}={order_id};a={amount_tiyin}"
    
    # Кодируем в Base64
    params_b64 = base64.b64encode(params.encode("utf-8")).decode("utf-8")
    
    # Итоговая ссылка
    return f"{settings.PAYME_URL}/{params_b64}"

def generate_click_link(order_id: int, amount_sum: int) -> str:
    """
    Генерация ссылки для перенаправления пользователя в Click.
    Формат: https://my.click.uz/services/pay?service_id={ID}&merchant_id={ID}&amount={SUM}&transaction_param={ORDER_ID}&return_url={URL}
    """
    base_url = "https://my.click.uz/services/pay"
    params = {
        "service_id": settings.CLICK_SERVICE_ID,
        "merchant_id": settings.CLICK_MERCHANT_ID,
        "amount": amount_sum,
        "transaction_param": order_id,
        "return_url": f"{settings.WEB_BASE_URL}/shop/order/success/{order_id}",
    }
    return f"{base_url}?{urlencode(params)}"
