"""JWT token encoding and decoding."""

from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from pydantic import BaseModel


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # Subject (email or user ID)
    exp: datetime  # Expiration time
    iat: datetime  # Issued at
    type: Literal["magic_link", "session"]


class TokenError(Exception):
    """Token validation error."""

    pass


def create_token(
    subject: str,
    secret: str,
    token_type: Literal["magic_link", "session"],
    expires_in: int,
) -> str:
    """Create a JWT token.

    Args:
        subject: Token subject (email or user ID).
        secret: JWT secret key.
        token_type: Type of token (magic_link or session).
        expires_in: Expiration time in seconds.

    Returns:
        Encoded JWT token string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "exp": now + timedelta(seconds=expires_in),
        "iat": now,
        "type": token_type,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> TokenPayload:
    """Decode and validate a JWT token.

    Args:
        token: Encoded JWT token string.
        secret: JWT secret key.

    Returns:
        Decoded token payload.

    Raises:
        TokenError: If token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise TokenError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise TokenError(f"Invalid token: {e}")
