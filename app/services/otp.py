import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.otp_challenge import OTPChallenge
from app.providers.otp.factory import get_otp_provider


def _create_verifier(
    challenge_id: int,
    phone: str,
    code: str,
) -> str:
    message = f"{challenge_id}:{phone}:{code}".encode()

    return hmac.new(
        settings.OTP_HMAC_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def request_otp(db: Session, phone: str) -> None:
    # Generate a cryptographically secure six-digit code.
    code = f"{secrets.randbelow(1_000_000):06d}"

    now = datetime.now(UTC)
    challenge = OTPChallenge(
        phone=phone,
        otp_hash="",
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        attempts=0,
    )

    try:
        db.add(challenge)
        db.flush()

        # flush() assigns the database ID without committing.
        challenge.otp_hash = _create_verifier(
            challenge.id,
            phone,
            code,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    try:
        provider = get_otp_provider()
        provider.send_otp(phone, code)

    except Exception:
        # Delivery failed. Invalidate this challenge so an
        # undelivered OTP cannot later be used.
        try:
            challenge.consumed_at = datetime.now(UTC)
            db.commit()
        except Exception:
            db.rollback()

        raise


def verify_otp(db: Session, phone: str, code: str) -> bool:
    now = datetime.now(UTC)

    try:
        # Lock the challenge row while we verify and consume it.
        challenge = (
            db.query(OTPChallenge)
            .filter(
                OTPChallenge.phone == phone,
                OTPChallenge.consumed_at.is_(None),
            )
            .order_by(OTPChallenge.created_at.desc())
            .with_for_update()
            .first()
        )

        # No unused challenge exists for this phone.
        if challenge is None:
            db.rollback()
            return False

        if challenge.consumed_at is not None:
            db.rollback()
            return False

        # Expired challenges must not be accepted.
        if challenge.expires_at <= now:
            challenge.consumed_at = now
            db.commit()
            return False

        # Stop accepting guesses after the configured limit.
        if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
            challenge.consumed_at = now
            db.commit()
            return False

        expected = _create_verifier(
            challenge.id,
            phone,
            code,
        )

        # Compare the verifier, not the original OTP.
        if not hmac.compare_digest(expected, challenge.otp_hash):
            challenge.attempts += 1

            # Invalidate the challenge when the limit is reached.
            if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
                challenge.consumed_at = now

            db.commit()
            return False

        # Correct OTP: consume it so it cannot be reused.
        challenge.consumed_at = now
        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
