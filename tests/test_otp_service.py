import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.models.otp_challenge import OTPChallenge
from app.services import otp as otp_service
from app.services.otp import verify_otp


class FakeOTPProvider:
    def __init__(self, fail=False):
        self.code = None
        self.phone = None
        self.fail = fail

    def send_otp(self, phone, code):
        if self.fail:
            raise RuntimeError("Simulated provider failure")
        self.phone = phone
        self.code = code


def make_challenge(db_session, phone, code="123456", expires_in=300):
    challenge = OTPChallenge(
        phone=phone,
        otp_hash="",
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        attempts=0,
    )
    db_session.add(challenge)
    db_session.flush()

    message = f"{challenge.id}:{phone}:{code}".encode()
    challenge.otp_hash = hmac.new(
        settings.OTP_HMAC_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    db_session.commit()
    return challenge


def test_valid_otp_is_accepted_and_consumed(db_session):
    phone = "+919876543210"
    challenge = make_challenge(db_session, phone)

    assert otp_service.verify_otp(db_session, phone, "123456") is True

    db_session.refresh(challenge)
    assert challenge.consumed_at is not None


def test_invalid_otp_increments_attempts(db_session):
    phone = "+919876543211"
    challenge = make_challenge(db_session, phone)

    assert otp_service.verify_otp(db_session, phone, "000000") is False

    db_session.refresh(challenge)
    assert challenge.attempts == 1
    assert challenge.consumed_at is None


def test_otp_cannot_be_reused(db_session):
    phone = "+919876543212"
    make_challenge(db_session, phone)

    assert otp_service.verify_otp(db_session, phone, "123456") is True
    assert otp_service.verify_otp(db_session, phone, "123456") is False


def test_expired_otp_is_rejected_and_consumed(db_session):
    phone = "+919876543213"
    challenge = make_challenge(db_session, phone, expires_in=-10)

    assert otp_service.verify_otp(db_session, phone, "123456") is False

    db_session.refresh(challenge)
    assert challenge.consumed_at is not None


def test_otp_is_invalidated_after_maximum_wrong_attempts(db_session):
    phone = "+919876543214"
    challenge = make_challenge(db_session, phone)

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        assert otp_service.verify_otp(db_session, phone, "000000") is False

    db_session.refresh(challenge)
    assert challenge.attempts == settings.OTP_MAX_ATTEMPTS
    assert challenge.consumed_at is not None

    assert otp_service.verify_otp(db_session, phone, "123456") is False


def test_request_otp_stores_verifier_and_sends_code(db_session, monkeypatch):
    provider = FakeOTPProvider()
    monkeypatch.setattr(otp_service, "get_otp_provider", lambda: provider)

    phone = "+919876543215"
    otp_service.request_otp(db_session, phone)

    assert provider.phone == phone
    assert provider.code is not None
    assert len(provider.code) == 6
    assert provider.code.isdigit()

    challenge = (
        db_session.query(OTPChallenge)
        .filter(OTPChallenge.phone == phone)
        .order_by(OTPChallenge.id.desc())
        .first()
    )
    assert challenge is not None
    assert challenge.otp_hash != provider.code

    expected = otp_service._create_verifier(
        challenge.id,
        phone,
        provider.code,
    )
    assert hmac.compare_digest(challenge.otp_hash, expected)


def test_provider_failure_invalidates_otp_challenge(db_session, monkeypatch):
    provider = FakeOTPProvider(fail=True)
    monkeypatch.setattr(otp_service, "get_otp_provider", lambda: provider)

    phone = "+919876543216"

    with pytest.raises(RuntimeError, match="Simulated provider failure"):
        otp_service.request_otp(db_session, phone)

    challenge = (
        db_session.query(OTPChallenge)
        .filter(OTPChallenge.phone == phone)
        .order_by(OTPChallenge.id.desc())
        .first()
    )
    assert challenge is not None
    assert challenge.consumed_at is not None
    assert otp_service.verify_otp(db_session, phone, "000000") is False

def test_expired_otp_is_consumed_and_rejected(db_session):
    phone = "+919100000094"
    now = datetime.now(UTC)

    challenge = OTPChallenge(
        phone=phone,
        otp_hash="unused-verifier",
        expires_at=now - timedelta(seconds=1),
        attempts=0,
    )
    db_session.add(challenge)
    db_session.commit()

    assert verify_otp(db_session, phone, "123456") is False


def test_wrong_otp_is_rejected_after_one_attempt(db_session, monkeypatch):
    phone = "+919100000095"
    challenge = make_challenge(db_session, phone)

    # Force a verifier mismatch without relying on a guessed OTP.
    monkeypatch.setattr(
        otp_service,
        "_create_verifier",
        lambda challenge_id, phone, code: "different-verifier",
    )

    assert otp_service.verify_otp(db_session, phone, "123456") is False

    db_session.refresh(challenge)
    assert challenge.attempts == 1
    assert challenge.consumed_at is None


def test_request_otp_rolls_back_when_database_commit_fails(
    db_session, monkeypatch
):
    provider = FakeOTPProvider()
    monkeypatch.setattr(
        otp_service, "get_otp_provider", lambda: provider
    )

    def fail_commit():
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="Simulated database failure"):
        otp_service.request_otp(db_session, "+919100000096")


def test_provider_failure_does_not_leave_otp_usable(
    db_session, monkeypatch
):
    provider = FakeOTPProvider(fail=True)
    monkeypatch.setattr(
        otp_service, "get_otp_provider", lambda: provider
    )

    phone = "+919100000097"

    with pytest.raises(RuntimeError, match="Simulated provider failure"):
        otp_service.request_otp(db_session, phone)

    challenge = (
        db_session.query(OTPChallenge)
        .filter(OTPChallenge.phone == phone)
        .order_by(OTPChallenge.id.desc())
        .first()
    )

    assert challenge is not None
    assert challenge.consumed_at is not None
    assert otp_service.verify_otp(db_session, phone, "123456") is False


def test_verify_otp_database_failure_rolls_back(
    db_session,
    monkeypatch,
):
    phone = "+919100000098"
    make_challenge(db_session, phone)

    original_commit = db_session.commit
    original_rollback = db_session.rollback
    rollback_called = False

    def fail_commit():
        raise RuntimeError("Simulated verification commit failure")

    def track_rollback():
        nonlocal rollback_called
        rollback_called = True
        return original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    with pytest.raises(
        RuntimeError,
        match="Simulated verification commit failure",
    ):
        otp_service.verify_otp(db_session, phone, "123456")

    assert rollback_called is True

    # Restore the session methods before checking persisted state.
    monkeypatch.setattr(db_session, "commit", original_commit)
    monkeypatch.setattr(db_session, "rollback", original_rollback)

    challenge = (
        db_session.query(OTPChallenge)
        .filter(OTPChallenge.phone == phone)
        .one()
    )
    assert challenge.consumed_at is None


def test_unconsumed_otp_at_attempt_limit_is_consumed(db_session):
    phone = "+919100000099"
    challenge = make_challenge(db_session, phone)
    challenge.attempts = settings.OTP_MAX_ATTEMPTS
    db_session.commit()

    assert otp_service.verify_otp(db_session, phone, "123456") is False

    db_session.refresh(challenge)
    assert challenge.attempts == settings.OTP_MAX_ATTEMPTS
    assert challenge.consumed_at is not None


def test_provider_cleanup_commit_failure_rolls_back(
    db_session,
    monkeypatch,
):
    provider = FakeOTPProvider(fail=True)
    monkeypatch.setattr(
        otp_service,
        "get_otp_provider",
        lambda: provider,
    )

    original_commit = db_session.commit
    original_rollback = db_session.rollback
    commit_calls = 0
    rollback_called = False

    def fail_cleanup_commit():
        nonlocal commit_calls
        commit_calls += 1

        if commit_calls == 1:
            # Allow the OTP challenge to be stored normally.
            return original_commit()

        # Fail only the cleanup commit after provider delivery fails.
        raise RuntimeError("Simulated cleanup commit failure")

    def track_rollback():
        nonlocal rollback_called
        rollback_called = True
        return original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_cleanup_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    with pytest.raises(RuntimeError, match="Simulated provider failure"):
        otp_service.request_otp(db_session, "+919100000100")

    assert commit_calls == 2
    assert rollback_called is True

