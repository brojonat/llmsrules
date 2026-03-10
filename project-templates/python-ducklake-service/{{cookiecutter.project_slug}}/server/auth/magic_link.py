"""Magic link generation and verification."""

from urllib.parse import urlencode

from server.auth.jwt import TokenError, TokenPayload, create_token, decode_token
from server.config import Settings


def create_magic_link(email: str, settings: Settings, base_url: str) -> str:
    """Create a magic link URL for email authentication.

    Args:
        email: User's email address.
        settings: Application settings.
        base_url: Base URL of the application.

    Returns:
        Full magic link URL with JWT token.
    """
    token = create_token(
        subject=email,
        secret=settings.jwt_secret.get_secret_value(),
        token_type="magic_link",
        expires_in=settings.magic_link_expiry,
    )
    params = urlencode({"token": token})
    return f"{base_url.rstrip('/')}/auth/verify?{params}"


def verify_magic_link(token: str, settings: Settings) -> str:
    """Verify a magic link token and return the email.

    Args:
        token: JWT token from magic link URL.
        settings: Application settings.

    Returns:
        Email address from the token.

    Raises:
        TokenError: If token is invalid, expired, or wrong type.
    """
    payload: TokenPayload = decode_token(
        token,
        settings.jwt_secret.get_secret_value(),
    )

    if payload.type != "magic_link":
        raise TokenError("Invalid token type")

    return payload.sub
