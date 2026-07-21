from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import FileRecord


def force_join_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    """Generates the subscription force-join keyboard layout."""
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.button(text=f"📢 {ch['title']}", url=ch["invite_link"])
    builder.button(text="✅ I've Joined — Try Again", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()


def search_results_keyboard(
    results: Sequence[FileRecord], bot_username: str
) -> InlineKeyboardMarkup:
    """Generates a structured list of clickable buttons for matching search items."""
    builder = InlineKeyboardBuilder()
    for record in results:
        quality_tag = f" [{record.quality}]" if record.quality else ""
        year_tag = f" ({record.year})" if record.year else ""
        label = f"🎬 {record.title}{year_tag}{quality_tag}"[:60]
        builder.button(
            text=label,
            callback_data=f"get_file:{record.file_hash}",
        )
    builder.adjust(1)
    return builder.as_markup()


def file_delivery_keyboard(
    file_hash: str,
    bot_username: str,
    share_url: str = "",
) -> InlineKeyboardMarkup:
    """Generates control buttons for the delivered movie files."""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📥 Save to Saved Messages", callback_data=f"save_file:{file_hash}")
    
    tg_share_link = f"https://t.me/share/url?url=https://t.me/{bot_username}?start={file_hash}&text=Popcorn%20tayyar%20karo!%20Ye%20rahi%20aapki%20movie%20link%20🎬"
    builder.button(text="🔗 Share Link", url=tg_share_link)
    
    builder.button(text="🔍 Search Another", switch_inline_query_current_chat="")
    
    builder.adjust(1)
    return builder.as_markup()


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    """Generates the primary administrator control board navigation structure."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Statistics", callback_data="admin:stats")
    builder.button(text="📁 Index Files", callback_data="admin:index_mode")
    builder.button(text="🚫 Ban User", callback_data="admin:ban_user")
    builder.button(text="✅ Unban User", callback_data="admin:unban_user")
    builder.button(text="🔄 Clear Search Cache", callback_data="admin:clear_cache")
    builder.adjust(2)
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Generates the cancel button layout to exit admin states."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="admin:cancel")
    return builder.as_markup()