from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Unified declarative abstract base configuration class for relational entity mapping frameworks."""
    pass


class User(Base):
    """Maps structural parameters representing telegram clients interacting within the ecosystem."""
    
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256))
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    total_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Establish descriptive relational tracking references back to analytical interaction registries
    requests: Mapped[list[FileRequest]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.full_name!r}>"


class FileRecord(Base):
    """Maps explicit tracking metadata metrics representing physical multimedia assets uploaded to remote clusters."""
    
    __tablename__ = "file_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_id: Mapped[str] = mapped_column(String(256))
    file_unique_id: Mapped[str] = mapped_column(String(128))
    file_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(256), nullable=True)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    download_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Establish interactive back-population triggers tracking specific asset request profiles
    requests: Mapped[list[FileRequest]] = relationship(back_populates="file_record")

    def __repr__(self) -> str:
        return f"<FileRecord hash={self.file_hash!r} title={self.title!r}>"


class FileRequest(Base):
    """Maps sequential correlation records representing continuous database entry hits and downloads."""
    
    __tablename__ = "file_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    file_hash: Mapped[str] = mapped_column(String(64), ForeignKey("file_records.file_hash"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="requests")
    file_record: Mapped[FileRecord] = relationship(back_populates="requests")


class BannedUser(Base):
    """Maps system configuration exceptions representing blacklisted identifiers barred from standard operational workflows."""
    
    __tablename__ = "banned_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_by: Mapped[int] = mapped_column(BigInteger)
    banned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )