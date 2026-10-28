import time
from datetime import UTC, datetime

from app.models.user import User


def _make_user(db_session, phone):
    user = User(
        phone=phone,
        role="CITIZEN",
        is_active=True,
        is_verified=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_created_at_is_timezone_aware_and_current(db_session):
    before = datetime.now(UTC)
    user = _make_user(db_session, "+919100000501")
    db_session.refresh(user)

    assert user.created_at.tzinfo is not None
    assert before <= user.created_at <= datetime.now(UTC)


def test_created_at_is_not_frozen_at_import_time(db_session):
    first = _make_user(db_session, "+919100000502")
    time.sleep(0.05)
    second = _make_user(db_session, "+919100000503")

    assert second.created_at > first.created_at
