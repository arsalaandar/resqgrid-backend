import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _hash_token(token: str) -> str:
    """Hash a refresh token before storing or looking it up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    """Generate a cryptographically random opaque refresh token."""
    return secrets.token_urlsafe(48)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )


def _revoke_family(db: Session, family_id: str, now: datetime) -> None:
    """Revoke every still-active token in one session family."""
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def _revoke_all_user_sessions(db: Session, user_id: int, now: datetime) -> None:
    """Revoke every still-active refresh token the user holds, on any device."""
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def create_refresh_session(db: Session, user: User) -> tuple[str, datetime]:
    """Create a refresh-token session for a successfully authenticated user."""
    now = datetime.now(UTC)
    session_expiry = now + timedelta(days=settings.JWT_SESSION_ABSOLUTE_EXPIRE_DAYS)
    token_expiry = min(
        now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        session_expiry,
    )
    raw_token = _new_token()

    record = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        family_id=str(uuid4()),
        token_version=user.token_version,
        expires_at=token_expiry,
        session_expires_at=session_expiry,
        created_at=now,
    )

    try:
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return raw_token, token_expiry


def rotate_refresh_token(
    db: Session,
    raw_token: str,
) -> tuple[User, str, datetime]:
    """Rotate a refresh token once, rejecting expired or reused tokens."""
    now = datetime.now(UTC)

    try:
        record = db.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == _hash_token(raw_token))
            .with_for_update()
        )

        if record is None:
            raise _unauthorized()

        # A previously rotated or revoked token may indicate token theft.
        if record.revoked_at is not None:
            _revoke_family(db, record.family_id, now)
            db.commit()
            raise _unauthorized()

        if record.expires_at <= now or record.session_expires_at <= now:
            _revoke_family(db, record.family_id, now)
            db.commit()
            raise _unauthorized()

        user = db.scalar(
            select(User).where(User.id == record.user_id).with_for_update()
        )

        if user is None:
            _revoke_family(db, record.family_id, now)
            db.commit()
            raise _unauthorized()

        if not user.is_active or user.token_version != record.token_version:
            # The account was deactivated or its credentials changed. Every
            # session the user holds is now untrustworthy, not just this one.
            _revoke_all_user_sessions(db, user.id, now)
            db.commit()
            raise _unauthorized()

        new_expiry = min(
            now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
            record.session_expires_at,
        )

        new_raw_token = _new_token()
        replacement = RefreshToken(
            user_id=record.user_id,
            token_hash=_hash_token(new_raw_token),
            family_id=record.family_id,
            token_version=user.token_version,
            expires_at=new_expiry,
            session_expires_at=record.session_expires_at,
            created_at=now,
        )

        db.add(replacement)
        db.flush()

        record.revoked_at = now
        record.replaced_by_id = replacement.id
        db.commit()

        return user, new_raw_token, new_expiry

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Revoke a refresh token and its active session family."""
    now = datetime.now(UTC)

    try:
        record = db.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == _hash_token(raw_token))
            .with_for_update()
        )

        if record is None:
            return

        _revoke_family(db, record.family_id, now)
        db.commit()
    except Exception:
        db.rollback()
        raise
