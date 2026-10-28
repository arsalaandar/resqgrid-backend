import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
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


def _is_throttled(db: Session, phone: str, now: datetime) -> bool:
    """Return True when this phone has requested too many OTPs recently."""
    day_ago = now - timedelta(days=1)
    hour_ago = now - timedelta(hours=1)

    created_times = db.scalars(
        select(OTPChallenge.created_at).where(
            OTPChallenge.phone == phone,
            OTPChallenge.created_at >= day_ago,
        )
    ).all()

    if not created_times:
        return False

    newest = max(created_times)
    in_last_hour = sum(1 for created in created_times if created >= hour_ago)

    return (
        now - newest < timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
        or in_last_hour >= settings.OTP_MAX_REQUESTS_PER_HOUR
        or len(created_times) >= settings.OTP_MAX_REQUESTS_PER_DAY
    )


def request_otp(db: Session, phone: str) -> bool:
    """Create and send an OTP unless this phone is being throttled.

    Returns True when an OTP was sent and False when the request was
    throttled. Callers must give the same public response either way so the
    throttle cannot be used to probe phone numbers.
    """
    # Generate a cryptographically secure six-digit code.
    code = f"{secrets.randbelow(1_000_000):06d}"

    now = datetime.now(UTC)
    challenge = OTPChallenge(
        phone=phone,
        otp_hash="",
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        attempts=0,
        # Use the application clock so the throttle compares like with like.
        created_at=now,
    )

    try:
        # Serialise concurrent requests for the same phone so two parallel
        # calls cannot both pass the throttle check. The lock is released
        # automatically at commit or rollback.
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:phone))"),
            {"phone": phone},
        )

        if _is_throttled(db, phone, now):
            db.rollback()
            return False

        # Only the newest OTP may be valid. Requesting a new code must not
        # leave older codes (with their own attempt counters) usable.
        db.execute(
            update(OTPChallenge)
            .where(
                OTPChallenge.phone == phone,
                OTPChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

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

    return True


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
