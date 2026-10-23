from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

# The algorithm is fixed by our backend.
# Never choose it based on an untrusted token.
JWT_ALGORITHM = "HS256"


def create_access_token(
    user_id: int,
    token_version: int = 0,
) -> str:
    """Create a signed JWT for an authenticated user."""
    now = datetime.now(UTC)

    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Verify a JWT and return its claims."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={
            "require": ["sub", "ver", "iss", "aud", "iat", "exp"],
        },
    )
