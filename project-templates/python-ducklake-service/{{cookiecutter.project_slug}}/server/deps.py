"""FastAPI dependencies."""

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from server.auth import Session, get_session
from server.config import Settings, get_settings
from server.data import LakeConnection, get_connection
from server.data.app_db import AppDB, get_app_db


def get_settings_dep() -> Settings:
    """Dependency for application settings."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_lake_dep() -> LakeConnection:
    """Dependency for DuckLake connection."""
    return get_connection()


LakeDep = Annotated[LakeConnection, Depends(get_lake_dep)]


def get_app_db_dep() -> AppDB:
    """Dependency for app database connection."""
    return get_app_db()


AppDbDep = Annotated[AppDB, Depends(get_app_db_dep)]


async def get_current_session(
    session_id: Annotated[str | None, Cookie(alias="session")] = None,
) -> Session | None:
    """Get current session from cookie (optional)."""
    if not session_id:
        return None
    return await get_session(session_id)


OptionalSessionDep = Annotated[Session | None, Depends(get_current_session)]


async def require_session(
    session: OptionalSessionDep,
    settings: SettingsDep,
) -> Session:
    """Require authenticated session."""
    if settings.dev_mode:
        # Auto-authenticate in dev mode (stable UUIDs for consistency)
        from datetime import datetime, timedelta, timezone

        return Session(
            session_id="00000000-0000-0000-0000-000000000000",
            user_id="00000000-0000-0000-0000-000000000001",
            email="dev@localhost",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session


SessionDep = Annotated[Session, Depends(require_session)]


def get_base_url(request: Request) -> str:
    """Get base URL from request."""
    return str(request.base_url).rstrip("/")


BaseUrlDep = Annotated[str, Depends(get_base_url)]
