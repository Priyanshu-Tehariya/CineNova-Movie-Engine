from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.cache.redis_client import redis_incr_with_ttl
from bot.config import settings

logger = structlog.get_logger(__name__)
THROTTLE_TEXT = "⏳ You're sending too many requests.\nPlease wait a moment and try again."


class RateLimitMiddleware(BaseMiddleware):
    """Middleware responsible for enforcing request rate limiting on inbound user messages using Redis."""

    def __init__(
        self,
        messages: int = settings.RATE_LIMIT_MESSAGES,
        window: int = settings.RATE_LIMIT_WINDOW,
    ) -> None:
        self.limit = messages
        self.window = window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        user = event.from_user
        # Bypass rate limiting restrictions for authorized bot administrators
        if user.id in settings.ADMIN_IDS:
            return await handler(event, data)

        # Increment and track the request counter for the user session within the TTL window
        key = f"rl:{user.id}"
        count = await redis_incr_with_ttl(key, self.window)

        # Restrict execution flow and notify the user if the request thresholds are exceeded
        if count > self.limit:
            logger.warning("rate_limit_triggered", user_id=user.id, count=count, limit=self.limit)
            try:
                await event.answer(THROTTLE_TEXT)
            except Exception:
                pass
            return

        return await handler(event, data)