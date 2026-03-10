"""Authentication: JWT, magic links, and sessions."""

from server.auth.jwt import TokenPayload, create_token, decode_token
from server.auth.magic_link import create_magic_link, verify_magic_link
from server.auth.session import (
    Session,
    create_session,
    get_session,
    invalidate_session,
)

__all__ = [
    "create_token",
    "decode_token",
    "TokenPayload",
    "create_magic_link",
    "verify_magic_link",
    "create_session",
    "get_session",
    "invalidate_session",
    "Session",
]
