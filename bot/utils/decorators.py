from __future__ import annotations

from functools import wraps
from typing import Callable

from aiogram.types import Message

from bot.config import settings


def admin_only(handler: Callable) -> Callable:
    """
    A structural route decorator that restricts handler execution exclusively to authorized administrators.
    
    Checks the inbound message user identifier against the configured ADMIN_IDS matrix mapping layout.
    """
    @wraps(handler)
    async def wrapper(message: Message, *args, **kwargs):
        # Enforce validation criteria by cross-referencing user context with administrative configurations
        if message.from_user and message.from_user.id in settings.ADMIN_IDS:
            return await handler(message, *args, **kwargs)
        
        # Deny request downstream access paths and push localized warning flags back to session logs
        await message.answer("⛔ Access denied.")
    return wrapper