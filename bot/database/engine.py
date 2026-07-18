from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import settings

# Initialize the persistent asynchronous engine connection pool layout configuration
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

# Construct the primary thread-safe session generator binding factory context
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager that allocates an isolated asynchronous database session pipeline handler.
    
    Automates transactional isolation tracking by enforcing commits, fallbacks, and socket closures.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            # Enforce systemic transactional rollbacks on downstream pipeline failure exceptions
            await session.rollback()
            raise
        finally:
            # Guarantee persistent socket connection closure to protect the driver thread pool
            await session.close()