from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.cache.redis_client import redis_delete, redis_set
from bot.config import settings


async def verify_and_cache_subscription(bot: Bot, user_id: int) -> bool:
    """
    Evaluates membership status across mandatory channels and caches positive subscription states.
    
    :param bot: The active Telegram Bot instance executing the client operations.
    :param user_id: Unique numeric Telegram identifier of the target user to evaluate.
    :return: Boolean indicating whether the user satisfies all subscription constraints.
    """
    for channel in settings.FORCE_JOIN_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            return False

    # Store successful authentication validation flags into the Redis instance session
    cache_key = f"fj:{user_id}"
    await redis_set(cache_key, "1", settings.FORCE_JOIN_CACHE_TTL)
    return True


async def invalidate_subscription_cache(user_id: int) -> None:
    """Purges the cached subscription verification flag for the specified user from Redis storage."""
    await redis_delete(f"fj:{user_id}")