from __future__ import annotations

import asyncio
import logging
import sys
import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from bot.cache.redis_client import close_redis, get_redis
from bot.config import settings
from bot.database.engine import engine, get_session
from bot.database.models import Base
from bot.handlers import admin, callbacks, search, start
from bot.middlewares.force_join import ForceJoinMiddleware
from bot.middlewares.logging_mw import StructuredLoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.db_middleware import EnsureUserExistsMiddleware  # 👈 Added Middleware Import


def configure_logging() -> None:
    """Configures structured and standard logging sinks based on environmental variables."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.LOG_JSON:
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    )


async def recover_file_sizes_background(bot: Bot) -> None:
    """Performs a non-blocking background sweep to resolve corrupted or unmeasured database file metrics."""
    logger = structlog.get_logger(__name__)
    try:
        logger.info("STARTING_BACKGROUND_REAL_FILE_SIZE_RECOVERY_FOR_OLD_FILES...")
        async with get_session() as session:
            from sqlalchemy import select
            from bot.database.models import FileRecord
            
            stmt = select(FileRecord).where((FileRecord.file_size == 0) | (FileRecord.file_size == None))
            db_result = await session.execute(stmt)
            corrupted_files = db_result.scalars().all()
            
            if not corrupted_files:
                logger.info("NO_0B_FILES_FOUND_DATABASE_IS_ALREADY_CLEAN")
                return

            logger.info(f"FOUND_{len(corrupted_files)}__FILES_WITH_0B_SIZE_FIXING_NOW...")
            storage_channel_id = int(settings.STORAGE_CHANNEL_ID)
            
            for f_rec in corrupted_files:
                try:
                    # Enforce anti-flood spacing restrictions across network transmissions
                    await asyncio.sleep(0.3)
                    
                    fallback_admin = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 7735364198
                    
                    tg_msg = await bot.forward_message(
                        chat_id=int(fallback_admin),
                        from_chat_id=storage_channel_id,
                        message_id=f_rec.message_id,
                        disable_notification=True
                    )
                    
                    await bot.delete_message(chat_id=int(fallback_admin), message_id=tg_msg.message_id)
                    
                    tg_file = tg_msg.video or tg_msg.document or tg_msg.audio
                    if tg_file and tg_file.file_size:
                        f_rec.file_size = tg_file.file_size
                        logger.info(f"SUCCESSFULLY_FIXED_SIZE_FOR: {f_rec.title} -> {tg_file.file_size} bytes")
                except Exception as inner_ex:
                    logger.error(f"COULD_NOT_FETCH_SIZE_FOR_MSG_{f_rec.message_id}", error=str(inner_ex))
            
            await session.commit()
            logger.info("ALL_OLD_FILES_SIZES_UPDATED_SUCCESSFULLY IN BACKGROUND!")
    except Exception as script_exc:
        logger.error("SIZE_RECOVERY_SCRIPT_FAILED", error=str(script_exc))


async def on_startup(bot: Bot) -> None:
    """Verifies infrastructure dependencies and initiates internal workers during system deployment."""
    logger = structlog.get_logger(__name__)

    try:
        r = await get_redis()
        await r.ping()
        logger.info("redis_connected", url=settings.REDIS_URL)
    except Exception as exc:
        logger.critical("redis_connection_failed", error=str(exc))
        raise

    try:
        async with engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy", fromlist=["text"]).text("SELECT 1")
            )
        logger.info("database_connected")

        from bot.database.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_created_successfully")

        # Inject the asynchronous recovery sequence task thread worker pool mapping loop
        asyncio.create_task(recover_file_sizes_background(bot))

    except Exception as exc:
        logger.critical("database_connection_failed", error=str(exc))
        raise

    me = await bot.get_me()
    logger.info(
        "bot_started",
        bot_id=me.id,
        username=me.username,
        environment="production",
    )


async def on_shutdown(bot: Bot) -> None:
    """Closes all distributed infrastructure connections and connection pools cleanly during teardown."""
    logger = structlog.get_logger(__name__)
    await close_redis()
    await engine.dispose()
    logger.info("bot_shutdown_complete")


async def main() -> None:
    """Configures application instances, mounts runtime middlewares, and triggers polling sequences."""
    configure_logging()
    logger = structlog.get_logger(__name__)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    redis_client = await get_redis()
    storage = RedisStorage(redis=redis_client)
    dp = Dispatcher(storage=storage)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Middlewares Pipeline
    dp.update.outer_middleware(StructuredLoggingMiddleware())
    dp.update.outer_middleware(EnsureUserExistsMiddleware())  # 👈 Added User Auto-Registration Middleware
    
    dp.message.middleware(ThrottlingMiddleware(limit=0.8, max_alerts=3))

    dp.message.middleware(ForceJoinMiddleware(bot=bot))
    dp.callback_query.middleware(ForceJoinMiddleware(bot=bot))
    dp.inline_query.middleware(ForceJoinMiddleware(bot=bot))

    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(callbacks.router)
    dp.include_router(search.router)

    logger.info("starting_polling")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    except Exception as exc:
        logger.critical("polling_crashed", error=str(exc))
        raise
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())