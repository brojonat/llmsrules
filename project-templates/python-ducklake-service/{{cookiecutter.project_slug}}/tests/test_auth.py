"""JWT authentication unit tests.

conftest.py sets required environment variables before server imports.
"""

from server.auth.jwt import TokenError, create_token, decode_token


def test_create_and_decode_token():
    """Test token creation and decoding round-trip."""
    secret = "test-secret-key"
    token = create_token(
        subject="test@example.com",
        secret=secret,
        token_type="magic_link",
        expires_in=900,
    )

    payload = decode_token(token, secret)
    assert payload.sub == "test@example.com"
    assert payload.type == "magic_link"


def test_decode_token_wrong_secret():
    """Test that decoding with wrong secret raises TokenError."""
    token = create_token(
        subject="test@example.com",
        secret="correct-secret",
        token_type="session",
        expires_in=3600,
    )

    try:
        decode_token(token, "wrong-secret")
        assert False, "Should have raised TokenError"
    except TokenError:
        pass


def test_decode_expired_token():
    """Test that expired tokens raise TokenError."""
    token = create_token(
        subject="test@example.com",
        secret="test-secret",
        token_type="magic_link",
        expires_in=-1,  # Already expired
    )

    try:
        decode_token(token, "test-secret")
        assert False, "Should have raised TokenError"
    except TokenError as e:
        assert "expired" in str(e).lower()


def test_token_types():
    """Test both magic_link and session token types."""
    secret = "test-secret"

    for token_type in ("magic_link", "session"):
        token = create_token(
            subject="user@example.com",
            secret=secret,
            token_type=token_type,
            expires_in=3600,
        )
        payload = decode_token(token, secret)
        assert payload.type == token_type
