from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a secure password hash for database storage."""
    if not password or not password.strip():
        raise ValueError("Password cannot be blank.")

    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")

    if len(password) > 1024:
        raise ValueError("Password is too long.")

    return _password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against its stored hash."""
    if not password or not stored_hash:
        return False

    try:
        return _password_hash.verify(password, stored_hash)
    except (ValueError, TypeError, UnknownHashError):
        return False


# Verified against when the account does not exist (or has no password), so
# that every login attempt costs one full hash verification and response time
# does not reveal which phone numbers belong to staff accounts.
_DUMMY_HASH = _password_hash.hash("timing-equalizer-password")


def verify_password_timing_safe(
    password: str,
    stored_hash: str | None,
) -> tuple[bool, str | None]:
    """Verify a password in roughly constant time.

    Returns ``(is_valid, upgraded_hash)``. ``upgraded_hash`` is a new hash to
    store when the old one used outdated parameters, otherwise ``None``.
    When ``stored_hash`` is missing the work is still done against a dummy
    hash and the result is always ``(False, None)``.
    """
    candidate = stored_hash or _DUMMY_HASH

    try:
        is_valid, upgraded_hash = _password_hash.verify_and_update(
            password or "",
            candidate,
        )
    except (ValueError, TypeError, UnknownHashError):
        return False, None

    if not stored_hash or not password:
        return False, None

    return is_valid, upgraded_hash
