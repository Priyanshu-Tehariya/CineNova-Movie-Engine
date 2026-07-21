from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select

# Import your DB User model from models.py
from bot.database.models import User as DBUser 


class EnsureUserExistsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Extract the incoming Telegram user and active DB session from event data
        user: User | None = data.get("event_from_user")
        session = data.get("session")  # Your DB Session

        # Process only if a valid human user and DB session exist
        if user and session and not user.is_bot:
            try:
                # 1. Check if the user already exists in the 'users' table
                stmt = select(DBUser).where(DBUser.id == user.id)
                result = await session.execute(stmt)
                db_user = result.scalar_one_or_none()

                # 2. If user is missing, insert them into 'users' table first
                if not db_user:
                    new_user = DBUser(
                        id=user.id,
                        username=user.username,
                        first_name=user.first_name
                    )
                    session.add(new_user)
                    await session.commit()
            except Exception as e:
                await session.rollback()
                print(f"[Middleware Error] Failed to auto-register user: {e}")

        # Pass execution to the next handler/middleware in line
        return await handler(event, data)