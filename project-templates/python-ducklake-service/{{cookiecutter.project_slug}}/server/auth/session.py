"""Session management."""

import uuid
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel


class Session(BaseModel):
    """User session data."""

    session_id: str
    user_id: str
    email: str
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class SessionStore(Protocol):
    """Protocol for session storage backends."""

    async def save(self, session: Session) -> None:
        """Save a session."""
        ...

    async def get(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete a session."""
        ...


# In-memory session store for development
_sessions: dict[str, Session] = {}


async def create_session(
    user_id: str,
    email: str,
    expires_in: int,
    store: SessionStore | None = None,
) -> Session:
    """Create a new session.

    Args:
        user_id: User's unique identifier.
        email: User's email address.
        expires_in: Session expiration time in seconds.
        store: Optional session store (defaults to in-memory).

    Returns:
        Created session.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    session = Session(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        email=email,
        created_at=now,
        expires_at=now + timedelta(seconds=expires_in),
    )

    if store:
        await store.save(session)
    else:
        _sessions[session.session_id] = session

    return session


async def get_session(
    session_id: str,
    store: SessionStore | None = None,
) -> Session | None:
    """Get a session by ID.

    Args:
        session_id: Session identifier.
        store: Optional session store (defaults to in-memory).

    Returns:
        Session if found and not expired, None otherwise.
    """
    if store:
        session = await store.get(session_id)
    else:
        session = _sessions.get(session_id)

    if session and not session.is_expired:
        return session

    return None


async def invalidate_session(
    session_id: str,
    store: SessionStore | None = None,
) -> None:
    """Invalidate (delete) a session.

    Args:
        session_id: Session identifier.
        store: Optional session store (defaults to in-memory).
    """
    if store:
        await store.delete(session_id)
    else:
        _sessions.pop(session_id, None)
