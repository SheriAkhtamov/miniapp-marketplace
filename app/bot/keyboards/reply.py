from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_phone_kb(lang: str = "ru"):
    text = "📱 Поделиться контактом" if lang == "ru" else "📱 Telefon raqamni yuborish"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=text, request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# Localized button labels
MENU_BUTTONS = {
    "ru": {"menu": "📋 Меню", "change_lang": "🌐 Сменить язык"},
    "uz": {"menu": "📋 Menyu", "change_lang": "🌐 Tilni o'zgartirish"},
}

def get_menu_kb(lang: str = "ru"):
    labels = MENU_BUTTONS.get(lang, MENU_BUTTONS["ru"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=labels["menu"])],
            [KeyboardButton(text=labels["change_lang"])]
        ],
        resize_keyboard=True
    )