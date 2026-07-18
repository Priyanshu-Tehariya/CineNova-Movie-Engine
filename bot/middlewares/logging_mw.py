from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

logger = structlog.get_logger(__name__)


class StructuredLoggingMiddleware(BaseMiddleware):
    """Middleware responsible for intercepting updates to inject bound structured loggers and trace processing metrics."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.perf_counter()
        update: Update | None = data.get("update")
        user_id: int | None = None
        event_type = "unknown"

        # Extract contextual attributes from the inbound Telegram update payload
        if update:
            if update.message:
                user_id = update.message.from_user.id if update.message.from_user else None
                event_type = "message"
            elif update.callback_query:
                user_id = update.callback_query.from_user.id if update.callback_query.from_user else None
                event_type = "callback_query"
            elif update.inline_query:
                user_id = update.inline_query.from_user.id if update.inline_query.from_user else None
                event_type = "inline_query"

        # Bind tracing parameters dynamically into the handler workflow context data
        bound_logger = logger.bind(user_id=user_id, event_type=event_type)
        data["logger"] = bound_logger

        try:
            result = await handler(event, data)
            elapsed = (time.perf_counter() - start) * 1000
            bound_logger.debug("request_handled", elapsed_ms=round(elapsed, 2))
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            bound_logger.exception("handler_exception", elapsed_ms=round(elapsed, 2), error=str(exc))
            raise