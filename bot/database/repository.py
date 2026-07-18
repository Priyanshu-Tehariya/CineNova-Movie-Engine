from __future__ import annotations

from datetime import datetime
from typing import Optional
import re

import structlog
from sqlalchemy import func, select, text, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import BannedUser, FileRecord, FileRequest, User

logger = structlog.get_logger(__name__)


class UserRepository:
    """Repository layer managing database transactions and abstractions for User entities."""
    
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create(
        self, user_id: int, full_name: str, username: Optional[str] = None
    ) -> tuple[User, bool]:
        """Fetches an existing user record or creates a new one if it does not exist."""
        result = await self._s.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.full_name = full_name
            user.username = username
            user.last_seen = datetime.utcnow()
            return user, False

        user = User(id=user_id, full_name=full_name, username=username)
        self._s.add(user)
        await self._s.flush()
        logger.info("new_user_registered", user_id=user_id, name=full_name)
        return user, True

    async def is_banned(self, user_id: int) -> bool:
        """Checks if the user identifier exists within the BannedUser restriction registry table."""
        result = await self._s.execute(
            select(BannedUser.id).where(BannedUser.id == user_id)
        )
        return result.scalar_one_or_none() is not None

    async def ban(self, user_id: int, banned_by: int, reason: Optional[str] = None) -> None:
        """Appends a constraint restriction entry mapping for the specified user record."""
        existing = await self._s.execute(
            select(BannedUser).where(BannedUser.id == user_id)
        )
        if existing.scalar_one_or_none():
            return
        self._s.add(BannedUser(id=user_id, reason=reason, banned_by=banned_by))
        await self._s.flush()

    async def unban(self, user_id: int) -> None:
        """Removes the ban configuration constraint entries and drops operational block flags."""
        result = await self._s.execute(
            select(BannedUser).where(BannedUser.id == user_id)
        )
        record = result.scalar_one_or_none()
        if record:
            await self._s.delete(record)
        await self._s.execute(
            update(User).where(User.id == user_id).values(is_banned=False)
        )
        await self._s.flush()

    async def total_count(self) -> int:
        """Returns the total aggregated number of registered users inside the database schema."""
        result = await self._s.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def increment_requests(self, user_id: int) -> None:
        """Increments the analytical user counter tracker tracking continuous system interactions."""
        await self._s.execute(
            update(User)
            .where(User.id == user_id)
            .values(total_requests=User.total_requests + 1)
        )


class FileRepository:
    """Repository layer managing indexing logic and search operations for FileRecord entities."""
    
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_hash(self, file_hash: str) -> Optional[FileRecord]:
        """Retrieves a single active FileRecord mapped by its specific tracking payload hash key."""
        result = await self._s.execute(
            select(FileRecord).where(
                FileRecord.file_hash == file_hash,
                FileRecord.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> FileRecord:
        """Persists a new structured multimedia metadata index entry record into the database repository."""
        record = FileRecord(**kwargs)
        self._s.add(record)
        await self._s.flush()
        logger.info("file_indexed", hash=record.file_hash, title=record.title)
        return record

    async def increment_downloads(self, file_hash: str) -> None:
        """Increments the internal download asset execution metrics by targeted file hash string values."""
        await self._s.execute(
            update(FileRecord)
            .where(FileRecord.file_hash == file_hash)
            .values(download_count=FileRecord.download_count + 1)
        )

    async def full_text_search(
        self, query: str, limit: int = 8
    ) -> list[FileRecord]:
        """Performs optimized regex-cleaned keyword matching and fallback fuzzy text search matching profiles."""
        query_clean = query.strip().lower()
        words = [w.strip() for w in re.split(r'[\s\.]+', query_clean) if len(w.strip()) > 1]
        query_years = [w for w in words if w.isdigit() and len(w) == 4]

        if not words:
            return []

        # Filter out common definite articles from primary search keyword evaluation mappings
        important_words = [w for w in words if w != "the"]
        if not important_words:
            important_words = words

        conditions = ["is_active = true"]
        params = {"limit": limit}

        # PURE SQL LAYER: Trims out structural bracket metadata patterns directly at the database engine execution phase
        for i, word in enumerate(important_words):
            conditions.append(f"lower(regexp_replace(replace(title, '.', ' '), '\\[.*?\\]', '', 'g')) LIKE :w_{i}")
            params[f"w_{i}"] = f"%{word}%"

        # Explicit release year extraction logic injection
        if query_years:
            for j, yr in enumerate(query_years):
                conditions.append(f"lower(title) LIKE :yr_{j}")
                params[f"yr_{j}"] = f"%{yr}%"

        like_sql = text(
            f"""
            SELECT * FROM file_records 
            WHERE {" AND ".join(conditions)} 
            ORDER BY download_count DESC 
            LIMIT :limit
            """
        )
        
        result = await self._s.execute(like_sql, params)
        rows = result.fetchall()
        
        if rows:
            return [FileRecord(**dict(row._mapping)) for row in rows]

        # FALLBACK FUZZY DATABASE LOOKUP LAYER
        fuzzy_sql = text(
            """
            SELECT * FROM file_records
            WHERE is_active = true
              AND similarity(lower(regexp_replace(replace(title, '.', ' '), '\\[.*?\\]', '', 'g')), lower(:query)) >= 0.40
            ORDER BY similarity(lower(replace(title, '.', ' ')), lower(:query)) DESC
            LIMIT :limit
            """
        )
        result = await self._s.execute(fuzzy_sql, {"query": query_clean, "limit": limit})
        rows = result.fetchall()
        
        final_fuzzy_results = [FileRecord(**dict(row._mapping)) for row in rows] if rows else []
        
        if query_years and final_fuzzy_results:
            return [r for r in final_fuzzy_results if any(yr in r.title for yr in query_years)]
            
        return final_fuzzy_results

    async def log_request(self, user_id: int, file_hash: str) -> None:
        """Creates a relational analytic tracking log entries record and updates counter metrics downstream."""
        self._s.add(FileRequest(user_id=user_id, file_hash=file_hash))
        await self.increment_downloads(file_hash)
        await self._s.flush()

    async def total_files(self) -> int:
        """Returns the total aggregated counts of active non-restricted tracked files within database partitions."""
        result = await self._s.execute(
            select(func.count()).select_from(FileRecord).where(FileRecord.is_active == True)
        )
        return result.scalar_one()

    async def delete_by_hash(self, file_hash: str) -> None:
        """Permanently purges targeted indexing parameters and associated analytic logs from active database tracking configurations."""
        from sqlalchemy import delete
        from bot.database.models import FileRecord, FileRequest

        await self._s.execute(
            delete(FileRequest).where(FileRequest.file_hash == file_hash)
        )
        await self._s.execute(
            delete(FileRecord).where(FileRecord.file_hash == file_hash)
        )
        await self._s.flush()