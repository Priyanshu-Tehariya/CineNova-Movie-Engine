from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineQuery, Message, TelegramObject

from bot.config import settings
from bot.utils.keyboards import force_join_keyboard

logger = structlog.get_logger(__name__)
_EXEMPT_CALLBACKS = {"check_subscription"}
FORCE_JOIN_MSG = "👋 <b>Welcome!</b>\n\nTo use this bot you must join our channel(s) first.\nClick the button(s) below, then tap <b>✅ I've Joined</b>."


class ForceJoinMiddleware(BaseMiddleware):
    """Middleware to enforce channel subscription checks on incoming updates."""
    
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user, chat_id = self._extract(event)
        if user is None or user.id in settings.ADMIN_IDS:
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data in _EXEMPT_CALLBACKS:
            return await handler(event, data)

        if not settings.FORCE_JOIN_CHANNELS:
            return await handler(event, data)

        # Bypassing the Redis cache verification to enforce real-time API checks on every interaction
        not_joined = await self._get_unjoined_channels(user.id)
        if not not_joined:
            return await handler(event, data)

        # Dispatches the subscription prompt with target validation if the user left the required channels
        await self._send_join_prompt(user.id, chat_id, not_joined)
        return

    @staticmethod
    def _extract(event: TelegramObject):
        """Extracts the user object and chat identifier from different Telegram update types."""
        if isinstance(event, Message):
            return event.from_user, event.chat.id
        if isinstance(event, CallbackQuery):
            return event.from_user, event.message.chat.id if event.message else None
        if isinstance(event, InlineQuery):
            return event.from_user, None
        return None, None

    async def _get_unjoined_channels(self, user_id: int) -> list[dict]:
        """Verifies channel participation statuses and compiles missing channel metadata resources."""
        unjoined: list[dict] = []
        for channel in settings.FORCE_JOIN_CHANNELS:
            try:
                member = await self._bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status in ("left", "kicked", "banned"):
                    raise ValueError("Not a member")
            except (TelegramForbiddenError, TelegramBadRequest, ValueError, Exception):
                try:
                    chat = await self._bot.get_chat(channel)
                    invite = chat.invite_link or f"https://t.me/{channel.lstrip('@')}"
                    unjoined.append({"title": chat.title or channel, "invite_link": invite})
                except Exception as e:
                    logger.warning("force_join_chat_fetch_failed", channel=channel, error=str(e))
                    unjoined.append({"title": channel, "invite_link": f"https://t.me/{channel.lstrip('@')}"})
        return unjoined

    async def _send_join_prompt(self, user_id: int, chat_id: int | None, channels: list[dict]) -> None:
        """Sends the localized HTML subscription reminder interface markup payload."""
        target = chat_id or user_id
        try:
            await self._bot.send_message(
                chat_id=target,
                text=FORCE_JOIN_MSG,
                reply_markup=force_join_keyboard(channels),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("force_join_prompt_failed", user_id=user_id, error=str(exc))