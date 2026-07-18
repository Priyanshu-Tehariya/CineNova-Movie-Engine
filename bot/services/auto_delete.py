from __future__ import annotations

import asyncio
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings

logger = structlog.get_logger(__name__)
WARNING_TEXT = "⚠️ <b>Heads up!</b>\nThe file above will be deleted in <b>1 minute</b> due to copyright protection.\n📥 Please <b>forward it to your Saved Messages</b> now!"
DELETED_TEXT = "🗑️ The file has been automatically deleted to comply with copyright policy.\n🔍 You can request it again anytime."


async def schedule_auto_delete(
    bot: Bot,
    chat_id: int,
    file_message_id: int,
    notification_message_id: int,
) -> None:
    """Asynchronously schedules the removal of temporary media distribution payloads and alerts user channels."""
    timeout = settings.AUTO_DELETE_TIMEOUT
    warning_before = settings.AUTO_DELETE_WARNING_TIME

    # Delays thread execution loop until the dynamic warning time trigger is hit
    await asyncio.sleep(timeout - warning_before)

    warning_msg = None
    try:
        warning_msg = await bot.send_message(chat_id=chat_id, text=WARNING_TEXT, parse_mode="HTML")
    except Exception as exc:
        logger.warning("auto_delete_warning_failed", chat_id=chat_id, error=str(exc))

    # Remaining sleep interval configuration loop prior to strict destruction sequence
    await asyncio.sleep(warning_before)

    # Consolidate target transmission tracking points for batch execution removal
    deleted_ids = [file_message_id, notification_message_id]
    if warning_msg:
        deleted_ids.append(warning_msg.message_id)

    # Dispatches transactional block purge events for registered tracking identifiers
    for msg_id in deleted_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except TelegramBadRequest as exc:
            if "message to delete not found" in str(exc).lower():
                pass
            else:
                logger.warning("auto_delete_failed", chat_id=chat_id, message_id=msg_id, error=str(exc))
        except Exception as exc:
            logger.warning("auto_delete_unexpected_error", chat_id=chat_id, message_id=msg_id, error=str(exc))

    # Appends downstream post-purge confirmation receipts back to target session history
    try:
        await bot.send_message(chat_id=chat_id, text=DELETED_TEXT, parse_mode="HTML")
    except Exception as exc:
        logger.warning("auto_delete_final_notify_failed", chat_id=chat_id, error=str(exc))

    logger.info("auto_delete_complete", chat_id=chat_id, file_message_id=file_message_id)