from __future__ import annotations

import asyncio
from typing import Optional
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram.types import Message

from bot.config import settings
from bot.database.engine import get_session
from bot.database.models import FileRecord
from bot.database.repository import FileRepository, UserRepository
from bot.services.auto_delete import schedule_auto_delete
from bot.utils.hash_utils import generate_deep_link, generate_file_hash
from bot.utils.keyboards import file_delivery_keyboard

logger = structlog.get_logger(__name__)


async def index_file_from_message(
    message: Message,
    title: str,
    year: Optional[int] = None,
    genre: Optional[str] = None,
    quality: Optional[str] = None,
    language: Optional[str] = None,
) -> FileRecord:
    """Extracts internal technical asset markers from a message payload and indexes the entity record into storage."""
    file_id: str
    file_unique_id: str
    file_type: str
    file_size: Optional[int] = None
    duration: Optional[int] = None

    # Inspect the message object context to parse structural multimedia properties
    if message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        file_type = "video"
        file_size = message.video.file_size
        duration = message.video.duration
    elif message.document:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id
        file_type = "document"
        file_size = message.document.file_size
    elif message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
        file_type = "audio"
        file_size = message.audio.file_size
        duration = message.audio.duration
    else:
        raise ValueError("Unsupported file type in message")

    file_hash = generate_file_hash()
    caption = message.caption or ""

    # Commit the verified metadata object fields directly to the relational database session
    async with get_session() as session:
        repo = FileRepository(session)
        record = await repo.create(
            file_hash=file_hash,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_type=file_type,
            title=title,
            caption=caption,
            file_size=file_size,
            duration=duration,
            year=year,
            genre=genre,
            language=language,
            quality=quality,
            message_id=message.message_id,
            uploaded_by=message.from_user.id,
        )

    return record


async def deliver_file(bot: Bot, chat_id: int, user_id: int, file_hash: str, retries: int = 3) -> None:
    """Fetches targeted metadata schemes from database layers and dispatches the corresponding asset package."""
    async with get_session() as session:
        repo = FileRepository(session)
        record = await repo.get_by_hash(file_hash)

    if not record:
        await bot.send_message(chat_id=chat_id, text="❌ File not found or has been removed.")
        return

    share_url = generate_deep_link(file_hash, settings.BOT_USERNAME)
    keyboard = file_delivery_keyboard(file_hash, settings.BOT_USERNAME, share_url)
    caption_text = (
        f"🎬 <b>{record.title}</b>"
        + (f"\n📅 Year: {record.year}" if record.year else "")
        + (f"\n🎭 Genre: {record.genre}" if record.genre else "")
        + (f"\n🖥️ Quality: {record.quality}" if record.quality else "")
        + (f"\n🌐 Language: {record.language}" if record.language else "")
        + f"\n\n⏳ This file will be deleted in <b>{settings.AUTO_DELETE_TIMEOUT // 60} minutes</b>.\n📥 Save it to your <b>Saved Messages</b> before then!"
    )

    delivered_msg: Optional[Message] = None

    # Executes a bounded execution loop to manage network transmission attempts across failure parameters
    for attempt in range(1, retries + 1):
        try:
            if record.file_type == "video":
                delivered_msg = await bot.send_video(chat_id=chat_id, video=record.file_id, caption=caption_text, parse_mode="HTML", reply_markup=keyboard)
            elif record.file_type == "document":
                delivered_msg = await bot.send_document(chat_id=chat_id, document=record.file_id, caption=caption_text, parse_mode="HTML", reply_markup=keyboard)
            elif record.file_type == "audio":
                delivered_msg = await bot.send_audio(chat_id=chat_id, audio=record.file_id, caption=caption_text, parse_mode="HTML", reply_markup=keyboard)
            break

        except TelegramRetryAfter as exc:
            if attempt == retries:
                raise
            wait = exc.retry_after + (2 ** attempt)
            logger.warning("telegram_rate_limit_hit", retry_after=exc.retry_after, backoff=wait, attempt=attempt)
            await asyncio.sleep(wait)

        except TelegramBadRequest as exc:
            logger.error("telegram_bad_request", file_hash=file_hash, error=str(exc))
            await bot.send_message(chat_id=chat_id, text="❌ Failed to retrieve file. Please try again later.")
            return

    if delivered_msg is None:
        return

    # Log systemic interaction frequencies and metrics down to target analytical repositories
    async with get_session() as session:
        file_repo = FileRepository(session)
        user_repo = UserRepository(session)
        await file_repo.log_request(user_id=user_id, file_hash=file_hash)
        await user_repo.increment_requests(user_id)

    notify_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"✅ File delivered! It will be <b>automatically deleted</b> in <b>{settings.AUTO_DELETE_TIMEOUT // 60} minutes</b>.\n💾 Forward it to your <b>Saved Messages</b> now.",
        parse_mode="HTML",
    )

    # Allocates a decoupled task thread to handle self-destruction lifecycles independently
    asyncio.create_task(
        schedule_auto_delete(
            bot=bot,
            chat_id=chat_id,
            file_message_id=delivered_msg.message_id,
            notification_message_id=notify_msg.message_id,
        )
    )
    logger.info("file_delivered", user_id=user_id, file_hash=file_hash, title=record.title)