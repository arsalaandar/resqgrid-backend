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
