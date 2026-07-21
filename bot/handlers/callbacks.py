from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import settings
from bot.services.file_store import deliver_file
from bot.services.search_service import invalidate_search_cache
from bot.services.subscription import verify_and_cache_subscription
from bot.handlers.start import WELCOME_TEXT

router = Router(name="callbacks")
logger = structlog.get_logger(__name__)


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery) -> None:
    """Evaluates channel subscription metrics and routes authorized client sessions downstream."""
    user_id = callback.from_user.id
    await callback.answer("🔄 Checking your subscriptions...", show_alert=False)
    
    is_member = await verify_and_cache_subscription(callback.bot, user_id)

    if is_member:
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        await callback.message.answer(
            WELCOME_TEXT.format(
                name=settings.BOT_USERNAME,
                timeout=settings.AUTO_DELETE_TIMEOUT // 60,
            ),
            parse_mode="HTML",
        )
    else:
        await callback.answer(
            "❌ You still haven't joined all required channels.\nPlease join them and try again.",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("get_file:"))
async def cb_get_file(callback: CallbackQuery) -> None:
    """Extracts unique asset keys from the interaction query and triggers the file delivery framework."""
    file_hash = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    await callback.answer("📥 Fetching your file...")
    logger.info("file_requested_via_callback", user_id=user_id, file_hash=file_hash)

    await deliver_file(
        bot=callback.bot,
        chat_id=chat_id,
        user_id=user_id,
        file_hash=file_hash,
    )


@router.callback_query(F.data.startswith("save_file:") | F.data.startswith("save_remind:"))
async def cb_save_remind(callback: CallbackQuery) -> None:
    """Dispatches actionable storage routing guidelines to the current interactive context session."""
    await callback.answer(
        "💾 Forward this file to your Saved Messages to keep it permanently!\nTap the file → Forward → Saved Messages",
        show_alert=True,
    )


@router.callback_query(F.data == "do_search")
async def cb_do_search(callback: CallbackQuery) -> None:
    """Prompts instructions for general search interaction inputs."""
    await callback.answer()
    await callback.message.answer("🔍 Just type the name of a movie to search!")


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    """Validates authorization constraints and pushes system performance parameters to the admin display."""
    if callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("⛔ Access denied.", show_alert=True)
        return

    from bot.database.engine import get_session
    from bot.database.repository import FileRepository, UserRepository

    async with get_session() as session:
        u_count = await UserRepository(session).total_count()
        f_count = await FileRepository(session).total_files()

    await callback.answer(
        f"👥 Users: {u_count:,}\n📁 Files: {f_count:,}",
        show_alert=True,
    )


@router.callback_query(F.data == "admin:clear_cache")
async def cb_clear_cache(callback: CallbackQuery) -> None:
    """Validates systemic clearance permissions and purges allocated search indexing caches entirely."""
    if callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("⛔ Access denied.", show_alert=True)
        return

    await invalidate_search_cache()
    await callback.answer("✅ Search cache cleared!", show_alert=True)


@router.callback_query(F.data == "admin:cancel")
async def cb_admin_cancel(callback: CallbackQuery) -> None:
    """Closes and removes the active administration markup layout cleanly from history partitions."""
    await callback.answer("Cancelled.")
    try:
        await callback.message.delete()
    except Exception:
        pass


# ─── 🛡️ AUTOMATED ACTION TICKETING SYSTEM FOR REQUEST DASHBOARD ───
@router.callback_query(F.data.startswith("req:"))
async def cb_admin_request_action(callback: CallbackQuery) -> None:
    """Intercepts custom asset request tickers and updates transactional verification statuses."""
    _, action, target_user_id, movie_name = callback.data.split(":", 3)
    target_user_id = int(target_user_id)
    
    if callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("⛔ Access Denied.", show_alert=True)
        return

    lines = callback.message.text.split("\n")
    user_line = lines[2] if len(lines) > 2 else f"👤 User: {target_user_id}"
    movie_line = lines[3] if len(lines) > 3 else f"🎬 Movie: Requested"

    if action == "done":
        new_text = (
            "🚨 <b>MOVIE REQUEST PROCESSED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{user_line}\n"
            f"{movie_line}\n"
            "📅 <b>Status:</b> 🟢 Completed (Uploaded)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=None)
        await callback.answer("✅ Ticket Closed: Uploaded")
        
        user_notification = (
            "🎬 <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "🎉 <b>Requested Movie Available!</b>\n"
            "🎬 <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "🔥 Great news! Your requested movie has been uploaded successfully. You can search for it directly now!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥 Aapki requested movie ab bot par available hai. Ab aap direct naam likh kar search kar sakte hain!\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
        )
        try:
            await callback.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode="HTML")
        except Exception:
            pass

    elif action == "soon":
        new_text = (
            "🚨 <b>MOVIE REQUEST PROCESSED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{user_line}\n"
            f"{movie_line}\n"
            "📅 <b>Status:</b> 🔵 Upcoming / Not Released\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=None)
        await callback.answer("⏳ Ticket Closed: Coming Soon")
        
        user_notification = (
            "⏳ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "⚠️ <b>Movie Release Status Update</b>\n"
            "⏳ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "📢 The movie you requested has not been officially released yet. It will be uploaded automatically as soon as the print becomes available.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📢 Aapki requested movie abhi officially release nahi hui hai. Jaise hi iska HD/Digital print aayega, sabse pehle upload kar diya jayega.\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
        )
        try:
            await callback.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode="HTML")
        except Exception:
            pass

    elif action == "skip":
        new_text = (
            "🚨 <b>MOVIE REQUEST PROCESSED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{user_line}\n"
            f"{movie_line}\n"
            "📅 <b>Status:</b> 🔴 Rejected\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=None)
        await callback.answer("❌ Ticket Closed: Rejected")
        
        user_notification = (
            "❌ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "⚠️ <b>Movie Request Cancelled</b>\n"
            "❌ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "🚫 Your request has been declined. Please ensure you didn't request a Web Series. Double-check the spelling/year and try again.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚫 Aapki movie request cancel kar di gayi hai. Dhyan rakhein bot Web Series support nahi karta. Movie ka naam aur spelling check karke dobara try karein.\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
        )
        try:
            await callback.bot.send_message(chat_id=target_user_id, text=user_notification, parse_mode="HTML")
        except Exception:
            pass