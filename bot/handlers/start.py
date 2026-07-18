from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.config import settings
from bot.database.engine import get_session
from bot.database.repository import UserRepository
from bot.services.file_store import deliver_file

router = Router(name="start")
logger = structlog.get_logger(__name__)

WELCOME_TEXT = (
    "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
    "👋 <b>Welcome to {name}!</b>\n"
    "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
    "🎬 <b>What can I do?</b>\n"
    "I am optimized to find and deliver <b>Movies</b> instantly!\n\n"
    "❌ <b>Note:</b> This bot does <u>NOT</u> support or contain Web Series.\n"
    "👉 Just type the <b>Movie Name</b> to search.\n\n"
    "⚠️ <i>All files are automatically deleted after {timeout} minutes for copyright compliance.</i>\n\n"
    "🤖 <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
    "🎬 <b>Main kya kar sakta hu?</b>\n"
    "Main aapke liye <b>Movies</b> dhoondne ke liye taiyar kiya gaya hu!\n\n"
    "❌ <b>Note:</b> Is bot mein Web Series <u>NAHI</u> milegi.\n"
    "👉 Bas mujhe kisi bhi <b>Movie ka Naam</b> likh kar bhejiye.\n\n"
    "⚠️ <i>Copyright niyamon ke kaaran saari files {timeout} minute mein automatic delete ho jayengi.</i>\n"
    "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
)


@router.message(CommandStart(deep_link=False))
async def cmd_start(message: Message) -> None:
    """Handles the standard /start command interaction to register new profiles and display welcoming guidelines."""
    user = message.from_user
    if not user:
        return

    async with get_session() as session:
        repo = UserRepository(session)
        _, created = await repo.get_or_create(
            user_id=user.id,
            full_name=user.full_name,
            username=user.username,
        )

    await message.answer(
        WELCOME_TEXT.format(
            name=settings.BOT_USERNAME,
            timeout=settings.AUTO_DELETE_TIMEOUT // 60,
        ),
        parse_mode="HTML",
    )

    if created:
        logger.info("new_user_start", user_id=user.id, name=user.full_name)


@router.message(CommandStart(deep_link=True, deep_link_encoded=False))
async def cmd_start_deep_link(message: Message, command) -> None:
    """Intercepts parameterized deep-linking tokens to perform authentication steps and fetch linked file assets."""
    user = message.from_user
    if not user:
        return

    async with get_session() as session:
        repo = UserRepository(session)
        _, created = await repo.get_or_create(
            user_id=user.id,
            full_name=user.full_name,
            username=user.username,
        )

    payload: str = command.args

    # Validate structural integrity constraints before executing data layer lookups
    if not payload or not payload.startswith("file_"):
        await message.answer(
            "❌ Invalid or expired link.\n🔍 Try searching for the file instead."
        )
        return

    logger.info(
        "deep_link_accessed",
        user_id=user.id,
        payload=payload,
        new_user=created,
    )

    processing_msg = await message.answer("🔄 Fetching your file, please wait...")

    try:
        # Route processing down into delivery workflows to transmit requested document payloads
        await deliver_file(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=user.id,
            file_hash=payload,
        )
    except Exception as exc:
        logger.exception("deep_link_delivery_failed", user_id=user.id, error=str(exc))
        await message.answer("❌ Something went wrong. Please try again later.")
    finally:
        try:
            await processing_msg.delete()
        except Exception:
            pass