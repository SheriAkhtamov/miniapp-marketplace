"""
Background service: checks how many users have blocked the bot.
Runs every 24 hours, stores the count in Redis.
"""
import asyncio
from typing import Optional
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound, TelegramBadRequest
from sqlalchemy import select

from app.utils.logger import logger
from app.utils.cache import cache_get, cache_set
from app.database.core import async_session_maker
from app.database.models import User

CACHE_KEY = "blocked_users_count"
CACHE_TTL = 86400  # 24 hours
CHECK_INTERVAL = 86400  # 24 hours


async def check_blocked_users(bot) -> int:
    """
    Iterate over all users with telegram_id and try getChat.
    Returns count of users who blocked the bot.
    """
    blocked = 0
    total = 0

    async with async_session_maker() as session:
        stmt = select(User.telegram_id).where(
            User.role == "user",
            User.telegram_id.isnot(None)
        )
        result = await session.execute(stmt)
        telegram_ids = [row[0] for row in result.all()]

    for tid in telegram_ids:
        total += 1
        try:
            await bot.get_chat(chat_id=tid)
        except (TelegramForbiddenError, TelegramNotFound):
            # User blocked the bot or deleted account
            blocked += 1
        except TelegramBadRequest:
            # Chat not found / invalid
            blocked += 1
        except Exception:
            # Network or other transient error — skip, don't count as blocked
            pass

        # Small delay to avoid Telegram rate limits
        if total % 30 == 0:
            await asyncio.sleep(1.0)

    logger.info(f"Blocked users check: {blocked}/{total} users blocked the bot")
    return blocked


async def blocked_users_loop(bot):
    """Background loop: check blocked users every 24 hours."""
    # Initial delay — let the app fully start
    await asyncio.sleep(10)

    while True:
        try:
            count = await check_blocked_users(bot)
            await cache_set(CACHE_KEY, count, ttl=CACHE_TTL)
            logger.info(f"Blocked users count cached: {count}")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in blocked_users_loop")

        await asyncio.sleep(CHECK_INTERVAL)


async def get_blocked_users_count() -> Optional[int]:
    """Read cached blocked users count. Returns None if not yet checked."""
    return await cache_get(CACHE_KEY)
