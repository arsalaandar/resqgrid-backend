from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.otp_challenge import OTPChallenge
from app.services import otp as otp_service

BASE_URL = "/api/v1/auth/citizen"


class RecordingProvider:
    def __init__(self):
        self.sent = []

    def send_otp(self, phone, code):
        self.sent.append((phone, code))


@pytest.fixture
def provider(monkeypatch):
    recorder = RecordingProvider()
    monkeypatch.setattr(otp_service, "get_otp_provider", lambda: recorder)
    return recorder


def challenges_for(db_session, phone):
    return db_session.scalars(
        select(OTPChallenge)
        .where(OTPChallenge.phone == phone)
        .order_by(OTPChallenge.id)
    ).all()


def age_challenges(db_session, phone, delta):
    for challenge in challenges_for(db_session, phone):
        challenge.created_at = challenge.created_at - delta
    db_session.commit()


def test_first_request_is_sent(db_session, provider):
    assert otp_service.request_otp(db_session, "+919100000601") is True
    assert len(provider.sent) == 1


def test_second_request_inside_cooldown_is_throttled(db_session, provider):
    phone = "+919100000602"

    assert otp_service.request_otp(db_session, phone) is True
    assert otp_service.request_otp(db_session, phone) is False

    assert len(provider.sent) == 1
    assert len(challenges_for(db_session, phone)) == 1


def test_request_after_cooldown_is_sent(db_session, provider):
    phone = "+919100000603"

    assert otp_service.request_otp(db_session, phone) is True
    age_challenges(
        db_session,
        phone,
        timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS + 1),
    )

    assert otp_service.request_otp(db_session, phone) is True
    assert len(provider.sent) == 2


def test_hourly_cap_blocks_further_requests(db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(settings, "OTP_MAX_REQUESTS_PER_HOUR", 3)
    phone = "+919100000604"

    results = [otp_service.request_otp(db_session, phone) for _ in range(4)]

    assert results == [True, True, True, False]
    assert len(provider.sent) == 3


def test_daily_cap_blocks_even_when_hour_is_quiet(db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(settings, "OTP_MAX_REQUESTS_PER_HOUR", 100)
    monkeypatch.setattr(settings, "OTP_MAX_REQUESTS_PER_DAY", 3)
    phone = "+919100000605"

    for _ in range(3):
        assert otp_service.request_otp(db_session, phone) is True

    # Move those requests out of the last hour but keep them inside the day.
    age_challenges(db_session, phone, timedelta(hours=2))

    assert otp_service.request_otp(db_session, phone) is False


def test_requests_older_than_a_day_do_not_count(db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(settings, "OTP_MAX_REQUESTS_PER_DAY", 1)
    phone = "+919100000606"

    assert otp_service.request_otp(db_session, phone) is True
    age_challenges(db_session, phone, timedelta(days=1, minutes=1))

    assert otp_service.request_otp(db_session, phone) is True


def test_throttle_is_per_phone(db_session, provider):
    assert otp_service.request_otp(db_session, "+919100000607") is True
    assert otp_service.request_otp(db_session, "+919100000608") is True
    assert len(provider.sent) == 2


def test_new_request_invalidates_the_previous_code(db_session, provider, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    phone = "+919100000609"

    assert otp_service.request_otp(db_session, phone) is True
    first_code = provider.sent[-1][1]

    assert otp_service.request_otp(db_session, phone) is True
    second_code = provider.sent[-1][1]

    first, second = challenges_for(db_session, phone)
    assert first.consumed_at is not None
    assert second.consumed_at is None

    # The superseded code is rejected even if it is correct for its challenge.
    if first_code != second_code:
        assert otp_service.verify_otp(db_session, phone, first_code) is False
    assert otp_service.verify_otp(db_session, phone, second_code) is True


def test_requesting_new_codes_cannot_reset_the_guess_budget(
    db_session, provider, monkeypatch
):
    """Guesses per hour are bounded by (requests per hour * attempts)."""
    monkeypatch.setattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    phone = "+919100000610"

    sent = 0
    for _ in range(50):
        if otp_service.request_otp(db_session, phone):
            sent += 1

    assert sent == settings.OTP_MAX_REQUESTS_PER_HOUR


def test_provider_failure_still_counts_toward_the_throttle(db_session, monkeypatch):
    class FailingProvider:
        def send_otp(self, phone, code):
            raise RuntimeError("provider down")

    monkeypatch.setattr(otp_service, "get_otp_provider", lambda: FailingProvider())
    phone = "+919100000611"

    with pytest.raises(RuntimeError):
        otp_service.request_otp(db_session, phone)

    # The failed send is still recorded, so retries cannot be used to
    # hammer a paid provider.
    assert otp_service.request_otp(db_session, phone) is False


def test_created_at_uses_the_application_clock(db_session, provider):
    before = datetime.now(UTC)
    otp_service.request_otp(db_session, "+919100000612")
    after = datetime.now(UTC)

    (challenge,) = challenges_for(db_session, "+919100000612")
    assert before <= challenge.created_at <= after


@pytest.mark.asyncio
async def test_route_gives_the_same_response_when_throttled(auth_client, provider):
    payload = {"phone": "+919100000613"}

    first = await auth_client.post(f"{BASE_URL}/request-otp", json=payload)
    second = await auth_client.post(f"{BASE_URL}/request-otp", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(provider.sent) == 1
