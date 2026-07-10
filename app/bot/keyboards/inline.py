from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from app.config import settings

# Кнопки выбора языка
lang_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz")
    ]
])

# Главное меню с WebApp
def get_main_kb(user_id: int, lang: str = "ru"):
    """
    Генерирует кнопку магазина.
    Теперь ID пользователя не передается в GET-параметрах, 
    так как авторизация идет через initData внутри WebApp.
    """
    btn_text = "🛍 Магазин" if lang == "ru" else "🛍 Do'kon"
    
    # Стартовая ссылка на магазин открывает категории.
    web_app_url = f"{settings.WEB_BASE_URL}/shop/categories"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=btn_text, 
                web_app=WebAppInfo(url=web_app_url)
            )
        ]
    ])
