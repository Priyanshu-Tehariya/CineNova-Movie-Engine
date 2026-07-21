from __future__ import annotations

import asyncio
import structlog
import hashlib
from aiogram import F, Router, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import text

from bot.config import settings
from bot.database.engine import get_session
from bot.database.repository import FileRepository, UserRepository
from bot.services.search_service import invalidate_search_cache
from bot.utils.decorators import admin_only
from bot.utils.hash_utils import generate_deep_link
from bot.utils.keyboards import admin_panel_keyboard, cancel_keyboard

router = Router(name="admin")
logger = structlog.get_logger(__name__)


# ── 1. FSM STATES BOUNDARIES (All Admin Room Isolations) ──
class IndexState(StatesGroup):
    waiting_for_file = State()
    waiting_for_title = State()
    waiting_for_metadata = State()

class BanButtonState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_reason = State()

class UnbanButtonState(StatesGroup):
    waiting_for_user_id = State()

class BroadcastButtonState(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirm = State()  # 👈 Added dedicated confirmation state to prevent context loss


# ── 2. GLOBAL CANCEL STEP PROTECTION ──
@router.message(Command("cancel"))
@router.message(F.text.casefold() == "cancel")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    """Cancels the active Finite State Machine (FSM) admin process."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("⚠️ No active process is currently running.")
        return
    await state.clear()
    await message.answer("❌ The current process has been cancelled. You can reopen the panel using /admin.")


# ── 3. CORE ADMIN PANEL BUTTON LAYER ──
@router.message(Command("admin"))
@admin_only
async def admin_panel(message: Message) -> None:
    """Renders the primary administrator configuration panel dashboard."""
    async with get_session() as session:
        u_count = await UserRepository(session).total_count()
        f_count = await FileRepository(session).total_files()

    await message.answer(
        f"🛠 <b>Admin Panel</b>\n\n"
        f"👥 Total Users: <b>{u_count:,}</b>\n"
        f"📁 Total Files: <b>{f_count:,}</b>",
        reply_markup=admin_panel_keyboard(),
        parse_mode="HTML",
    )


# ── 3.5 📊 STATISTICS BUTTON LIVE POPUP HANDLER ──
@router.callback_query(lambda c: c.data and "stats" in c.data.lower())
async def cb_statistics_update(callback: CallbackQuery) -> None:
    """Triggers an alert popup containing real-time application database performance metrics."""
    async with get_session() as session:
        u_count = await UserRepository(session).total_count()
        f_count = await FileRepository(session).total_files()

    await callback.answer(
        text=f"📊 CineNova Live Statistics 📊\n\n"
             f"👥 Total Active Users: {u_count:,}\n"
             f"📁 Total Files Indexed: {f_count:,}\n\n"
             f"✨ System status is healthy.",
        show_alert=True
    )


# ── 4. BAN USER WORKING MODULE ──
@router.callback_query(lambda c: c.data and "ban" in c.data.lower() and "unban" not in c.data.lower())
async def cb_ban_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Initiates the administrative user restriction state flow."""
    await callback.answer()
    await callback.message.answer(
        "🚫 <b>Ban User Mode</b>\n\n"
        "Please send the numeric <b>Telegram User ID</b> of the target user:\n\n"
        "<i>(Type 'cancel' to abort the operation)</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(BanButtonState.waiting_for_user_id)

@router.message(BanButtonState.waiting_for_user_id, F.text)
async def process_ban_id(message: Message, state: FSMContext) -> None:
    """Validates the structure of the incoming target user identifier."""
    if message.text.strip().casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return
        
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Invalid format! Please enter a valid numeric Telegram User ID.")
        return
        
    target_id = int(message.text.strip())
    await state.update_data(target_id=target_id)
    await message.answer(
        "📝 Please provide the <b>Reason</b> for the ban (or type <code>skip</code> to proceed without a reason):",
        parse_mode="HTML"
    )
    await state.set_state(BanButtonState.waiting_for_reason)

@router.message(BanButtonState.waiting_for_reason, F.text)
async def finalize_ban_button(message: Message, state: FSMContext) -> None:
    """Commits the constraint configuration for the specified user record to storage."""
    if message.text.strip().casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return

    data = await state.get_data()
    target_id = data["target_id"]
    reason_text = message.text.strip()
    reason = None if reason_text.lower() == "skip" else reason_text

    async with get_session() as session:
        await UserRepository(session).ban(
            user_id=target_id,
            banned_by=message.from_user.id,
            reason=reason,
        )

    from bot.services.subscription import invalidate_subscription_cache
    await invalidate_subscription_cache(target_id)

    await message.answer(
        f"✅ User <code>{target_id}</code> has been successfully banned."
        + (f"\n📝 Reason: {reason}" if reason else ""),
        parse_mode="HTML",
    )
    await state.clear()


# ── 5. UNBAN USER WORKING MODULE (WITH SYSTEM AUTO-SYNC) ──
@router.callback_query(lambda c: c.data and "unban" in c.data.lower())
async def cb_unban_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Initiates the user record constraint removal flow."""
    await callback.answer()
    await callback.message.answer(
        "✅ <b>Unban User Mode</b>\n\n"
        "Please send the numeric <b>Telegram User ID</b> of the user you wish to unban:\n\n"
        "<i>(Type 'cancel' to abort the operation)</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(UnbanButtonState.waiting_for_user_id)

@router.message(UnbanButtonState.waiting_for_user_id, F.text)
async def process_unban_button(message: Message, state: FSMContext, bot: Bot) -> None:
    """Performs global cleanup and synchronizes external access keys for target user restoration."""
    if message.text.strip().casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return

    if not message.text.strip().isdigit():
        await message.answer("⚠️ Invalid format! Please enter a valid numeric Telegram User ID.")
        return

    target_id = int(message.text.strip())
    
    # 1. Core Database clean update
    async with get_session() as session:
        await UserRepository(session).unban(user_id=target_id)

    # 2. Redis search/subscription caching invalidation
    from bot.services.subscription import invalidate_subscription_cache
    await invalidate_subscription_cache(target_id)

    # 3. RAM Throttling middleware memory clear system lock fallback sync
    try:
        from bot.middlewares.throttling import ThrottlingMiddleware
        for middleware in message.middleware or []:
            if isinstance(middleware, ThrottlingMiddleware):
                middleware.caches.pop(str(target_id), None)
    except Exception:
        pass

    # 4. English professional text broadcast gateway to target user chat
    try:
        await bot.send_message(
            chat_id=target_id,
            text="🎉 <b>Good News!</b>\n\n"
                 "You have been <b>UNBANNED</b> by the administrator. You can now resume searching for movies and files on the bot.\n\n"
                 "<i>Please follow the rules and avoid spamming in the future! 😊</i>",
            parse_mode="HTML"
        )
        notification_status = "\n📢 <i>The user has been successfully notified about the unban status via direct message.</i>"
    except Exception:
        notification_status = "\n⚠️ <i>Failed to deliver direct notification to user (bot might be blocked), but cache and database records have been cleared.</i>"

    await message.answer(
        f"✅ User <code>{target_id}</code> has been successfully unbanned.{notification_status}", 
        parse_mode="HTML"
    )
    await state.clear()


# ── 6. BROADCAST MODULE WITH MULTI-ROUTING BROAD CATCH & PREVIEW ──
@router.callback_query(lambda c: c.data and "broadcast" in c.data.lower())
@router.message(Command("broadcast"))
async def cb_broadcast_start(event: CallbackQuery | Message, state: FSMContext) -> None:
    """Initializes the multi-user system announcement interface pipeline."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    await message.answer(
        "📢 <b>Broadcast Message Mode</b>\n\n"
        "Send the message payload you wish to distribute (Supports Text, Photo, Video, or Document media types). "
        "A validation preview configuration block will be generated prior to execution.\n\n"
        "<i>(Type 'cancel' to abort the operation)</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(BroadcastButtonState.waiting_for_message)

@router.message(BroadcastButtonState.waiting_for_message)
async def process_broadcast_button(message: Message, state: FSMContext) -> None:
    """Generates an operational staging preview block for confirmation verification."""
    if message.text and message.text.strip().casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return

    # Safely store message details in FSM memory
    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    
    confirm_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm & Send", callback_data="confirm_broadcast"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_broadcast")
            ]
        ]
    )

    await message.answer("👇 <b>Here is the structural layout preview of your message:</b>", parse_mode="HTML")
    await message.send_copy(chat_id=message.chat.id)
    
    await message.answer(
        "☝️ Please verify the preview content above. Do you want to broadcast this asset payload to all active users?",
        reply_markup=confirm_keyboard,
        parse_mode="HTML"
    )
    # Transition to confirmation state so inline buttons handle the next step
    await state.set_state(BroadcastButtonState.waiting_for_confirm)


@router.callback_query(F.data == "confirm_broadcast")
async def cb_confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Executes asynchronously managed data copying distribution to non-restricted accounts."""
    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    from_chat_id = data.get("broadcast_chat_id")
    
    # Clear FSM state immediately to avoid repeated processing
    await state.clear()

    if not msg_id or not from_chat_id:
        await callback.answer("❌ Context state missing, please restart /broadcast.", show_alert=True)
        return

    await callback.answer("🚀 Broadcasting started...")
    
    # Remove inline confirmation buttons upon execution
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    status_msg = await callback.message.answer("🔄 <i>Broadcasting message payload... Please wait.</i>", parse_mode="HTML")

    async with get_session() as session:
        result = await session.execute(text("SELECT id FROM users WHERE is_banned = false"))
        user_ids = [row[0] for row in result.fetchall()]

    if not user_ids:
        await status_msg.edit_text("❌ No active non-restricted users found in the repository.")
        return

    success, fail = 0, 0
    for u_id in user_ids:
        try:
            await bot.copy_message(chat_id=int(u_id), from_chat_id=int(from_chat_id), message_id=int(msg_id))
            success += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(chat_id=int(u_id), from_chat_id=int(from_chat_id), message_id=int(msg_id))
                success += 1
            except Exception:
                fail += 1
        except Exception:
            fail += 1

    await status_msg.edit_text(
        f"📢 <b>Broadcast Completed Successfully!</b>\n\n"
        f"✅ Delivered to: <b>{success} users</b>\n"
        f"❌ Failed (Blocked): <b>{fail} users</b>",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "cancel_broadcast")
async def cb_cancel_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Terminates active broadcast transaction allocations cleanly."""
    await callback.answer("Cancelled")
    await state.clear()
    try:
        await callback.message.edit_text("❌ The transmission broadcast process has been cancelled.")
    except Exception:
        await callback.message.answer("❌ The transmission broadcast process has been cancelled.")


# ── 7. MANUAL ADD FILE LINK (FIXED MULTI-ROUTING WITH CALLBACK) ──
@router.callback_query(lambda c: c.data and "index" in c.data.lower())
@router.message(Command("add"))
async def cmd_add_file(event: CallbackQuery | Message, state: FSMContext) -> None:
    """Initiates the data indexing flow for custom document tracking injection."""
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    await message.answer(
        "📁 <b>File Indexing Mode</b>\n\n"
        "Forward or directly upload the movie/file asset you wish to register in the database system context.\n\n"
        "<i>(Type 'cancel' to abort the operation)</i>",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(IndexState.waiting_for_file)

@router.message(IndexState.waiting_for_file, F.video | F.document | F.audio)
async def receive_file_for_index(message: Message, state: FSMContext) -> None:
    """Stores temporary file context coordinates and transitions to definition naming."""
    await state.update_data(file_message_id=message.message_id)
    await state.set_state(IndexState.waiting_for_title)
    await message.answer("✅ File asset received!\n\n📝 Now send the precise query <b>title</b> for this item:", parse_mode="HTML", reply_markup=cancel_keyboard())

@router.message(IndexState.waiting_for_title, F.text)
async def receive_title_for_index(message: Message, state: FSMContext) -> None:
    """Registers display identity details and initiates relational data parsing."""
    if message.text.strip().casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(IndexState.waiting_for_metadata)
    await message.answer(
        "📋 Optional metadata specifications (or type <code>skip</code>):\n\nFormat: <code>year|genre|quality|language</code>",
        parse_mode="HTML", reply_markup=cancel_keyboard()
    )

@router.message(IndexState.waiting_for_metadata, F.text)
async def receive_metadata_for_index(message: Message, state: FSMContext) -> None:
    """Extracts internal structural segment tokens and prompts payload asset verification."""
    text_data = message.text.strip()
    if text_data.casefold() == "cancel":
        await state.clear()
        await message.answer("❌ Process Cancelled.")
        return

    year = genre = quality = language = None
    if text_data.lower() != "skip":
        parts = [p.strip() for p in text_data.split("|")]
        if len(parts) >= 1 and parts[0].isdigit(): year = int(parts[0])
        if len(parts) >= 2: genre = parts[1]
        if len(parts) >= 3: quality = parts[2]
        if len(parts) >= 4: language = parts[3]

    await message.answer("🔄 Processing... please re-send or forward the original file once more to finalize tracking logic:", reply_markup=cancel_keyboard())
    await state.update_data(year=year, genre=genre, quality=quality, language=language, awaiting_final_file=True)

@router.message(IndexState.waiting_for_metadata, F.video | F.document | F.audio)
async def finalize_index(message: Message, state: FSMContext) -> None:
    """Validates structural constraints and signs unique identifier registry records to storage."""
    data = await state.get_data()
    if not data.get("awaiting_final_file"): return

    tg_file = message.video or message.document or message.audio
    if not tg_file:
        await message.answer("❌ Invalid file format structure encountered.")
        await state.clear()
        return

    f_id, f_unique_id = tg_file.file_id, tg_file.file_unique_id
    f_size = getattr(tg_file, "file_size", 0) or 0
    f_duration = getattr(tg_file, "duration", 0) or 0
    file_hash = hashlib.md5(f_unique_id.encode()).hexdigest()[:16]
    fallback_admin = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else message.from_user.id

    try:
        async with get_session() as session:
            file_repo = FileRepository(session)
            existing = await file_repo.get_by_hash(file_hash)
            if not existing:
                record = await file_repo.create(
                    title=data.get("title", "Unknown"), file_hash=file_hash, file_id=f_id, file_unique_id=f_unique_id,
                    file_type=message.content_type, caption=message.caption or data.get("title", "Unknown"),
                    file_size=int(f_size), duration=f_duration, message_id=message.message_id, uploaded_by=int(fallback_admin),
                    is_active=True, download_count=0, year=data.get("year"), genre=data.get("genre"), quality=data.get("quality"), language=data.get("language")
                )
            else:
                if not existing.file_size or existing.file_size == 0:
                    existing.file_size = int(f_size)
                    await session.commit()
                record = existing

        deep_link = generate_deep_link(record.file_hash, settings.BOT_USERNAME)
        await invalidate_search_cache()
        await message.answer(f"✅ <b>File indexed successfully!</b>\n\n🎬 Title: <b>{record.title}</b>\n🔑 Hash: <code>{record.file_hash}</code>\n🔗 Deep Link:\n{deep_link}", parse_mode="HTML")
    except Exception as exc:
        logger.exception("file_index_failed", error=str(exc))
        await message.answer(f"❌ Failed to index file: {exc}")
    finally:
        await state.clear()


# ── 8. CORE UTILITIES (MANUAL DELETE AND GETHASH) ──
@router.message(Command("delete"))
@admin_only
async def cmd_delete_file(message: Message) -> None:
    """Removes indexed mapping references explicitly by structural key hash query values."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("⚠️ <b>Usage:</b> <code>/delete &lt;file_hash&gt;</code>", parse_mode="HTML")
        return
    file_hash = parts[1].strip()
    async with get_session() as session:
        file_repo = FileRepository(session)
        record = await file_repo.get_by_hash(file_hash)
        if not record:
            await message.answer("❌ The requested file record was not found in the database directory.")
            return
        await file_repo.delete_by_hash(file_hash)
    await invalidate_search_cache()
    await message.answer(f"🗑️ <b>File Deleted Successfully!</b>\n\n🎬 Title: <b>{record.title}</b>", parse_mode="HTML")

@router.message(Command("gethash"))
@admin_only
async def get_file_hash_by_name(message: Message, command: CommandObject) -> None:
    """Executes full-text pattern resolution matching to identify unique token reference data configurations."""
    query = command.args
    if not query:
        await message.answer("❌ Please provide a movie name text criteria parameter string.")
        return
    async with get_session() as session:
        results = await FileRepository(session).full_text_search(query, limit=5)
        if not results:
            await message.answer("❌ No matching internal document target records found.")
            return
        response_text = "📊 <b>Matching Files & Hashes Found:</b>\n\n"
        for file in results:
            response_text += f"🎬 Title: <b>{file.title}</b>\n🔑 Hash ID: <code>{file.file_hash}</code>\n🗑️ Delete link: /delete {file.file_hash}\n───────────────────\n"
        await message.answer(response_text)


# ── 9. STORAGE CHANNEL AUTOMATIC INDEXING (UNTOUCHED REAL-SIZE ENGINE) ──
@router.channel_post()
async def auto_index_channel_post(message: Message, bot: Bot) -> None:
    """Automatically intercepts target remote media storage distributions and registers tracking schemas."""
    tg_file = message.video or message.document or message.audio
    if not tg_file: return
    if settings.STORAGE_CHANNEL_ID and message.chat.id != int(settings.STORAGE_CHANNEL_ID): return

    title = message.caption.strip() if message.caption else getattr(tg_file, "file_name", f"Auto Indexed Movie_{message.message_id}")
    f_id, f_unique_id = tg_file.file_id, tg_file.file_unique_id
    f_size = getattr(tg_file, "file_size", 0) or 0
    f_duration = getattr(tg_file, "duration", 0) or 0
    file_hash = hashlib.md5(f_unique_id.encode()).hexdigest()[:16]
    fallback_admin = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 7735364198

    try:
        async with get_session() as session:
            file_repo = FileRepository(session)
            existing = await file_repo.get_by_hash(file_hash)
            if not existing:
                record = await file_repo.create(
                    title=title, file_hash=file_hash, file_id=f_id, file_unique_id=f_unique_id, file_type=message.content_type,
                    caption=message.caption or title, file_size=int(f_size), duration=f_duration, message_id=message.message_id,
                    uploaded_by=int(fallback_admin), is_active=True, download_count=0
                )
            else:
                if not existing.file_size or existing.file_size == 0:
                    existing.file_size = int(f_size)
                    await session.commit()
                record = existing

        await invalidate_search_cache()
        log_channel_id = getattr(settings, "LOG_CHANNEL_ID", None)
        if log_channel_id:
            deep_link = generate_deep_link(record.file_hash, settings.BOT_USERNAME)
            for attempt in range(3):
                try:
                    await bot.send_message(
                        chat_id=int(log_channel_id),
                        text=f"📂 <b>Movie Auto-Indexed Successful!</b>\n\n🎬 Title: <b>{record.title}</b>\n🔑 Hash ID: <code>{record.file_hash}</code>\n\n🔗 Deep Link:\n{deep_link}",
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(2.0)
                    break
                except TelegramRetryAfter as e: await asyncio.sleep(e.retry_after + 1)
                except Exception: await asyncio.sleep(2)
    except Exception as exc:
        logger.exception("clean_auto_index_failed", error=str(exc))