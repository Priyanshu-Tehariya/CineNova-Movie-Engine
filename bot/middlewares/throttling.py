from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, Bot
from aiogram.types import Message
from aiogram.dispatcher.event.bases import CancelHandler
import structlog

logger = structlog.get_logger(__name__)

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 1.2, max_alerts: int = 3, window_reset: float = 2.5) -> None:
        """
        Initializes the anti-flood throttling configuration parameters.
        
        :param limit: Time threshold in seconds below which a message is classified as spam (Default: 1.2s).
        :param max_alerts: Maximum sequential warnings allowed prior to enforcing a permanent database ban (Strict 3).
        :param window_reset: Inactivity period in seconds required to fully reset the user alert counter (Default: 2.5s).
        """
        self.limit = limit
        self.max_alerts = max_alerts
        self.window_reset = window_reset
        self.caches: Dict[str, Dict[str, Any]] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not event.from_user or event.chat.type != "private":
            return await handler(event, data)

        user_id = event.from_user.id
        username = event.from_user.username or "No Username"
        full_name = event.from_user.full_name
        
        bot: Bot = data.get("bot") or event.bot
        if not bot:
            return await handler(event, data)

        # Admin Bypass: Exclude authorized administrators from rate-limiting mechanisms
        from bot.config import settings
        if settings.ADMIN_IDS and user_id in settings.ADMIN_IDS:
            return await handler(event, data)

        # ── LAYER 0: DATABASE REAL-TIME SYNCHRONIZATION VERIFICATION ──
        # Check database restriction records if the user is locally locked in memory to account for administrative unbans
        if str(user_id) in self.caches and self.caches[str(user_id)].get("is_banned_now"):
            from bot.database.engine import get_session
            from bot.database.repository import UserRepository
            async with get_session() as session:
                user_repo = UserRepository(session)
                is_still_banned = await user_repo.is_banned(user_id)
            
            if not is_still_banned:
                # Instantly drop memory-cached state flags if the constraint record is no longer active in storage
                self.caches.pop(str(user_id), None)
            else:
                raise CancelHandler()

        current_time = time.time()

        # Allocate dynamic structural logging cache fields for unrecognized new user context states
        if str(user_id) not in self.caches:
            self.caches[str(user_id)] = {"last_time": current_time, "alerts": 0, "is_banned_now": False}
            return await handler(event, data)

        user_data = self.caches[str(user_id)]
        time_diff = current_time - user_data["last_time"]
        
        # ── SMART WINDOW RESET MECHANISM ──
        # Reset current warning counts to zero if request intervals conform to standard operations thresholds
        if time_diff > self.window_reset:
            user_data["alerts"] = 0

        user_data["last_time"] = current_time  # Synchronize current timestamp metric instantly

        # ── SPAMMER DETECTION ENGINE LAYER ──
        if time_diff < self.limit:
            user_data["alerts"] += 1  # Increment sequential user constraint fault flags

            # Phase 1: Interactive Warnings Output Delivery
            if user_data["alerts"] < self.max_alerts:
                await event.answer(
                    f"⚠️ <b>Please do not spam!</b> Slow down, otherwise you will be banned automatically. (Warning {user_data['alerts']}/{self.max_alerts})",
                    parse_mode="HTML"
                )
                raise CancelHandler()  # Intercept transaction downstream execution to restrict asset retrieval

            # Phase 2: AUTOMATIC BAN TRIGGER ENFORCEMENT FOR FAULT LIMIT EXCEEDED
            user_data["is_banned_now"] = True  # Lock operational flags locally inside middleware memory state
            logger.warn("CRITICAL_SPAM_ATTACK_BAN_TRIGGERED", user_id=user_id, username=username, name=full_name)

            try:
                from bot.database.engine import get_session
                from bot.database.repository import UserRepository
                
                fallback_admin = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 7735364198
                async with get_session() as session:
                    user_repo = UserRepository(session)
                    await user_repo.ban(
                        user_id=user_id,
                        banned_by=int(fallback_admin),
                        reason="Strict Anti-Flood System Protection (3/3 Continuous Spam)"
                    )
                
                from bot.services.subscription import invalidate_subscription_cache
                await invalidate_subscription_cache(user_id)

                # Transmit absolute restriction feedback to targeted spam instance session channel
                await event.answer(
                    "🚫 <b>You have been PERMANENTLY BANNED</b> for overloading the bot and ignoring warnings!",
                    parse_mode="HTML"
                )

                # Real-Time Administrative Notification Pipeline Packaging
                alert_text = (
                    f"🚨 <b>ANTI-FLOOD AUTO BAN ALERT (VPS)</b> 🚨\n\n"
                    f"👤 <b>Name:</b> {full_name}\n"
                    f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                    f"🏷️ <b>Username:</b> @{username}\n"
                    f"📝 <b>Reason:</b> Continuous Bot Flooding Attempt ({user_data['alerts']}/{self.max_alerts} Warnings Crossed)\n"
                    f"🛡️ <b>Status:</b> Permanently Banned from Database & Thread Destroyed"
                )

                # Log Channel Push Distribution Routing
                log_channel_id = getattr(settings, "LOG_CHANNEL_ID", None)
                if log_channel_id:
                    try:
                        await bot.send_message(chat_id=int(log_channel_id), text=alert_text, parse_mode="HTML")
                    except Exception as e:
                        logger.error("failed_sending_to_log_channel", error=str(e))

                # Administrator Direct Private Inbox Urgent Notification Push
                if settings.ADMIN_IDS:
                    try:
                        await bot.send_message(chat_id=int(settings.ADMIN_IDS[0]), text=alert_text, parse_mode="HTML")
                    except Exception:
                        pass

                raise CancelHandler()  # Halt execution loop for current lifecycle transaction thread context

            except CancelHandler:
                raise
            except Exception as exc:
                logger.error("auto_ban_failed", error=str(exc))
                return

        return await handler(event, data)