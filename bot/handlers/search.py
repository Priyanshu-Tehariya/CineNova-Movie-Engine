from __future__ import annotations

import re
import difflib
import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from sqlalchemy import select

from bot.config import settings
from bot.database.engine import get_session
from bot.database.models import FileRecord
from bot.services.search_service import search_files
from bot.utils.keyboards import search_results_keyboard

router = Router(name="search")
logger = structlog.get_logger(__name__)

NO_RESULTS_TEXT = (
    "🔍 No results found for <b>{query}</b>.\n\n"
    "💡 Try different keywords, check the spelling, "
    "or search by year/genre."
)

RESULTS_HEADER = (
    "🔍 Found <b>{count}</b> result(s) for <b>{query}</b>.\n"
    "Tap a title below to get the file:"
)


def get_readable_file_size(size_in_bytes: int | None) -> str:
    """Converts file size in bytes into a human-readable format (KB, MB, GB)."""
    if not size_in_bytes or size_in_bytes <= 0:
        return "550 MB"  # Safe fallback default size
    
    size_float = float(size_in_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_float < 1024.0:
            return f"{size_float:.2f} {unit}"
        size_float /= 1024.0
    return f"{size_float:.2f} PB"


async def get_closest_suggestions(query: str) -> list[str]:
    """Fetches close-matching titles from the database for spell correction."""
    async with get_session() as session:
        stmt = select(FileRecord.title).distinct()
        res = await session.execute(stmt)
        all_titles = [row[0] for row in res.fetchall() if row[0]]
        
    if not all_titles:
        return []
    
    return difflib.get_close_matches(query, all_titles, n=3, cutoff=0.5)


@router.message(F.text & ~F.text.startswith("/"))
async def text_search(message: Message) -> None:
    """Handles direct text search queries from users."""
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("⚠️ Please enter at least 2 characters to search.")
        return

    user_id = message.from_user.id if message.from_user else 0
    logger.info("search_requested", user_id=user_id, query=query)

    results = await search_files(query)

    # Activate auto-correction engine if no exact results found
    if not results or len(results) == 0:
        suggestions = await get_closest_suggestions(query)
        
        if suggestions:
            suggest_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🎬 {s}", switch_inline_query_current_chat=s)]
                for s in suggestions
            ])
            
            await message.answer(
                f"🔍 No results found for <b>{query}</b>.\n\n"
                f"💡 <b>Did you mean? / Kya aapka matlab ye tha:</b>",
                reply_markup=suggest_keyboard,
                parse_mode="HTML"
            )
        else:
            await message.answer(
                NO_RESULTS_TEXT.format(query=query), parse_mode="HTML"
            )
        return

    # Process and build results keyboard if results exist
    class _Stub:
        def __init__(self, d: dict):
            self.__dict__.update(d)

    stubs = []
    async with get_session() as session:
        for r in results:
            f_hash = r.get("file_hash")
            db_size = 0
            
            if f_hash:
                stmt = select(FileRecord.file_size).where(FileRecord.file_hash == f_hash)
                db_res = await session.execute(stmt)
                db_size = db_res.scalar() or 0

            readable_size = get_readable_file_size(db_size)
            
            stub_data = r.copy()
            stub_data["title"] = f"[{readable_size}] {r['title']}"
            stubs.append(_Stub(stub_data))

    keyboard = search_results_keyboard(stubs, settings.BOT_USERNAME)

    await message.answer(
        RESULTS_HEADER.format(count=len(results), query=query),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.inline_query()
async def inline_search(query: InlineQuery) -> None:
    """Handles inline search queries for the bot."""
    search_term = query.query.strip()

    if len(search_term) < 2:
        await query.answer(
            results=[],
            switch_pm_text="Type to search for movies...",
            switch_pm_parameter="start",
            cache_time=1,
        )
        return

    results_data = await search_files(search_term)

    inline_results = []
    async with get_session() as session:
        for item in results_data:
            deep_link = f"https://t.me/{settings.BOT_USERNAME}?start={item['file_hash']}"
            quality_tag = f" [{item['quality']}]" if item.get("quality") else ""
            year_tag = f" ({item['year']})" if item.get("year") else ""
            genre_tag = f"\n🎭 {item['genre']}" if item.get("genre") else ""

            f_hash = item.get("file_hash")
            db_size = 0
            if f_hash:
                stmt = select(FileRecord.file_size).where(FileRecord.file_hash == f_hash)
                db_res = await session.execute(stmt)
                db_size = db_res.scalar() or 0

            readable_size = get_readable_file_size(db_size)

            description = (
                f"📦 Size: {readable_size} | 📅{year_tag}{genre_tag}\n"
                f"🖥️ {item.get('quality', 'Unknown quality')} | "
                f"⬇️ {item.get('download_count', 0)} downloads"
            )

            inline_results.append(
                InlineQueryResultArticle(
                    id=item["file_hash"],
                    title=f"🎬 [{readable_size}] {item['title']}{quality_tag}{year_tag}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"🎬 <b>{item['title']}</b>{quality_tag}{year_tag}\n"
                            f"📦 <b>Size:</b> {readable_size}\n"
                            f"🔗 <a href='{deep_link}'>Get this file →</a>"
                        ),
                        parse_mode="HTML",
                    ),
                    url=deep_link,
                )
            )

    await query.answer(
        results=inline_results,
        cache_time=settings.SEARCH_CACHE_TTL,
        is_personal=False,
    )


# ─── 📬 MULTILINGUAL MOVIE REQUEST HANDLER ───
@router.message(Command("request"))
async def cmd_request_movie(message: Message) -> None:
    """Processes incoming movie requests and forwards them to the admin channel."""
    movie_name = message.text.replace("/request", "").strip()
    
    if not movie_name or not re.search(r'\b(19|20)\d{2}\b', movie_name):
        error_msg = (
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "📖 <b>Movie Request Format / Sahi Tarika</b>\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "⚠️ <b>Year is mandatory / Year likhna zaroori hai!</b>\n\n"
            "Please use the command followed by movie name and year.\n"
            "📝 <i>Syntax:</i> <code>/request Movie Name (Year)</code>\n"
            "💡 <i>Example:</i> <code>/request Inception (2010)</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Kripya command ke baad movie ka naam aur year likhein.\n"
            "📝 <i>Tarika:</i> <code>/request Movie Name (Year)</code>\n"
            "💡 <i>Udaharan:</i> <code>/request Inception (2010)</code>\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
        )
        await message.answer(error_msg, parse_mode="HTML")
        return

    user = message.from_user
    user_id = user.id if user else 0
    user_name = user.full_name if user else "Unknown User"
    
    request_text = (
        "🚨 <b>NEW MOVIE REQUEST RECEIVED</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {user_name} (<code>{user_id}</code>)\n"
        f"🎬 <b>Movie:</b> <code>{movie_name}</code>\n"
        "📅 <b>Status:</b> ⏳ Pending Approval\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Uploaded", callback_data=f"req:done:{user_id}:{movie_name[:20]}"),
            InlineKeyboardButton(text="⏳ Coming Soon", callback_data=f"req:soon:{user_id}:{movie_name[:20]}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"req:skip:{user_id}:{movie_name[:20]}")
        ]
    ])
    
    try:
        await message.bot.send_message(
            chat_id=settings.REQUEST_CHANNEL_ID,
            text=request_text,
            reply_markup=admin_keyboard,
            parse_mode="HTML"
        )
        
        user_response = (
            "🤖 <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
            "🎯 <b>Request Submitted Successfully!</b>\n"
            "🤖 <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
            "Your request has been forwarded. You will be notified once uploaded!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Aapki request bhej di gayi hai. Movie upload hote hi notification mil jayega!\n"
            "✨ <b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
        )
        await message.answer(user_response, parse_mode="HTML")
    except Exception as e:
        logger.error("request_forward_failed", error=str(e))
        await message.answer("❌ Server error. Please try again later / Kripya thodi der baad try karein.")


# ─── 📥 SAVE TO SAVED MESSAGES CALLBACK HANDLER ───
@router.callback_query(F.data.startswith("save_file:"))
async def handle_save_to_saved_messages(callback: CallbackQuery) -> None:
    """Sends a permanent copy of the file to the user's private message history."""
    file_hash = callback.data.split(":")[1]
    
    async with get_session() as session:
        stmt = select(FileRecord).where(FileRecord.file_hash == file_hash)
        res = await session.execute(stmt)
        file_item = res.scalars().first()

    if not file_item:
        await callback.answer("❌ File not found in database!", show_alert=True)
        return

    try:
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=file_item.file_id, 
            caption=(
                f"📥 <b>Saved File:</b>\n"
                f"🎬 {file_item.title}\n\n"
                f"<i>This file is permanently saved in your chat history. It won't be auto-deleted.</i>"
            ),
            parse_mode="HTML"
        )
        await callback.answer("✅ File saved in your chat permanently!")
    except Exception as e:
        logger.error("save_file_direct_failed", error=str(e))
        await callback.answer("❌ Error. Please forward the above file manually!", show_alert=True)