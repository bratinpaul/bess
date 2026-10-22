"""fastapi-users wiring: the user database adapter (async SQLAlchemy over battery_users.app_user) and the user manager
(argon2 hashing through pwdlib, timing-safe authenticate, transparent hash upgrade)."""
import secrets
import uuid
from typing import AsyncGenerator

from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, get_async_session

password_helper = PasswordHelper(PasswordHash((Argon2Hasher(),)))  # argon2id only


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    # password reset / e-mail verification flows aren't exposed yet; the secrets only need to exist
    reset_password_token_secret = secrets.token_urlsafe(32)
    verification_token_secret = secrets.token_urlsafe(32)


async def get_user_db(session: AsyncSession = Depends(get_async_session)) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db, password_helper)
