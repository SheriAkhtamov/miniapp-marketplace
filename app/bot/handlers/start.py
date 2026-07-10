import re
from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database.models import User
from app.database.repositories.users import UserRepository
from app.bot.states import Registration
from app.bot.keyboards import inline, reply
from app.bot.keyboards.reply import MENU_BUTTONS
from app.utils.deeplinks import PHONE_REGISTRATION_START_PARAM

router = Router()


def _is_phone_registration_start(message: types.Message) -> bool:
    """Whether this /start came from the Mini App phone-request button."""
    parts = (message.text or "").split(maxsplit=1)
    return len(parts) == 2 and parts[1].strip() == PHONE_REGISTRATION_START_PARAM


async def _ask_for_missing_phone(message: types.Message, state: FSMContext, lang: str) -> None:
    """Switch the bot to contact-sharing mode and show Telegram's native button."""
    lang = lang if lang in ("ru", "uz") else "ru"
    await state.update_data(language=lang)
    await state.set_state(Registration.waiting_for_missing_phone)
    text = (
        "📱 Для продолжения работы отправьте ваш номер телефона 👇"
        if lang == "ru"
        else "📱 Davom etish uchun telefon raqamingizni yuboring 👇"
    )
    await message.answer(text, reply_markup=reply.get_phone_kb(lang))

@router.message(CommandStart())
async def cmd_start(message: types.Message, session: AsyncSession, state: FSMContext):
    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    # A Mini App can be opened before the regular registration flow has created
    # a user row. Its phone-request link must still lead directly to Telegram's
    # contact button rather than back to the language-selection screen.
    if _is_phone_registration_start(message) and not user:
        try:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.first_name,
                language="ru",
                role="user",
            )
            user_repo.add(user)
            await user_repo.commit()
        except IntegrityError:
            await session.rollback()
            user = await user_repo.get_by_telegram_id(message.from_user.id)

    if user:
        # Проверяем наличие телефона
        if not user.phone:
            lang = user.language or "ru"
            await _ask_for_missing_phone(message, state, lang)
            return

        # Пользователь уже есть, сразу даем доступ в магазин
        await message.answer(
            f"С возвращением, {user.username or message.from_user.first_name}! 👋\n"
            f"Xush kelibsiz, {user.username or message.from_user.first_name}!",
            reply_markup=reply.get_menu_kb(lang=user.language)
        )
        await message.answer(
            "🛍 Shop Mini App",
            reply_markup=inline.get_main_kb(user_id=message.from_user.id, lang=user.language)
        )
    else:
        # Начинаем регистрацию
        await state.set_state(Registration.choosing_language)
        await message.answer(
            "🇺🇿 Tilni tanlang / 🇷🇺 Выберите язык",
            reply_markup=inline.lang_kb
        )

# Обработка выбора языка
@router.callback_query(Registration.choosing_language, F.data.startswith("lang_"))
async def lang_chosen(callback: types.CallbackQuery, state: FSMContext):
    lang_code = callback.data.split("_")[1] # ru или uz
    await state.update_data(language=lang_code)
    
    await state.set_state(Registration.waiting_for_phone)
    
    text = "Пожалуйста, отправьте ваш номер телефона для регистрации 👇" if lang_code == "ru" else \
           "Ro'yxatdan o'tish uchun telefon raqamingizni yuboring 👇"
    
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=reply.get_phone_kb(lang_code))

# Обработка получения контакта
@router.message(Registration.waiting_for_phone, F.contact)
async def contact_received(message: types.Message, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")
    phone = re.sub(r'[^\d]', '', message.contact.phone_number)

    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        error_text = (
            "Пожалуйста, отправьте свой номер телефона через кнопку 👇"
            if lang == "ru"
            else "Iltimos, tugma orqali o'zingizning telefon raqamingizni yuboring 👇"
        )
        await message.answer(error_text, reply_markup=reply.get_phone_kb(lang))
        return
    
    # Создаем пользователя
    user_repo = UserRepository(session)
    
    try:
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if not user:
            new_user = User(
                telegram_id=message.from_user.id, 
                username=message.from_user.first_name,
                phone=phone,
                language=lang,
                role="user"
            )
            user_repo.add(new_user)
            await user_repo.commit()
        else:
            # Just update info
            user.phone = phone
            user.language = lang
            await user_repo.commit()
            
    except IntegrityError:
        await session.rollback()
        # Повторная попытка: пользователь уже создан в параллельном запросе
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if user:
            user.phone = phone
            user.language = lang
            await session.commit()
    
    await state.clear()
    
    welcome_text = "Вы успешно зарегистрированы! Нажмите кнопку ниже, чтобы открыть магазин 👇" if lang == "ru" else \
                   "Siz muvaffaqiyatli ro'yxatdan o'tdingiz! Do'konni ochish uchun pastdagi tugmani bosing 👇"
    
    await message.answer(
        welcome_text,
        reply_markup=reply.get_menu_kb(lang=lang)
    )
    
    await message.answer(
        "🛍 Shop Mini App",
        reply_markup=inline.get_main_kb(user_id=message.from_user.id, lang=lang)
    )

@router.message(F.text.in_([MENU_BUTTONS["ru"]["menu"], MENU_BUTTONS["uz"]["menu"]]))
async def menu_button(message: types.Message, session: AsyncSession, state: FSMContext):
    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    lang = user.language if user else "ru"
    name = user.username if user else message.from_user.first_name

    # Проверяем телефон
    if user and not user.phone:
        await _ask_for_missing_phone(message, state, lang)
        return

    await message.answer(
        f"С возвращением, {name}! 👋\n"
        f"Xush kelibsiz, {name}!",
        reply_markup=inline.get_main_kb(user_id=message.from_user.id, lang=lang)
    )

@router.message(F.text.in_([MENU_BUTTONS["ru"]["change_lang"], MENU_BUTTONS["uz"]["change_lang"]]))
async def change_language_button(message: types.Message, session: AsyncSession):
    await message.answer(
        "🇺🇿 Tilni tanlang / 🇷🇺 Выберите язык",
        reply_markup=inline.lang_kb
    )

# Обработка получения телефона от существующего пользователя без номера
@router.message(Registration.waiting_for_missing_phone, F.contact)
async def missing_phone_received(message: types.Message, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")
    phone = re.sub(r'[^\d]', '', message.contact.phone_number)

    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        error_text = (
            "Пожалуйста, отправьте свой номер телефона через кнопку 👇"
            if lang == "ru"
            else "Iltimos, tugma orqali o'zingizning telefon raqamingizni yuboring 👇"
        )
        await message.answer(error_text, reply_markup=reply.get_phone_kb(lang))
        return

    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if user:
        user.phone = phone
        await session.commit()

    await state.clear()

    ok_text = (
        "✅ Номер сохранён! Нажмите кнопку ниже, чтобы открыть магазин 👇"
        if lang == "ru"
        else "✅ Raqam saqlandi! Do'konni ochish uchun pastdagi tugmani bosing 👇"
    )
    await message.answer(ok_text, reply_markup=reply.get_menu_kb(lang=lang))
    await message.answer(
        "🛍 Shop Mini App",
        reply_markup=inline.get_main_kb(user_id=message.from_user.id, lang=lang)
    )

@router.callback_query(F.data.startswith("lang_"))
async def lang_change_callback(callback: types.CallbackQuery, session: AsyncSession):
    lang_code = callback.data.split("_")[1]
    if lang_code not in ("ru", "uz"):
        await callback.answer()
        return

    user_repo = UserRepository(session)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)
    if user:
        user.language = lang_code
        await session.commit()

    await callback.message.delete()

    confirm = "✅ Язык изменён на русский" if lang_code == "ru" else "✅ Til o'zbekchaga o'zgartirildi"
    await callback.message.answer(confirm, reply_markup=reply.get_menu_kb(lang=lang_code))
    await callback.answer()
