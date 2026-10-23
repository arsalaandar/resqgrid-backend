
from unittest.mock import Mock

import pytest

from app.models.user import User
from app.services import refresh_tokens


def test_create_refresh_session_rolls_back_on_database_error():
    db = Mock()
    user = User(id=1, role="CITIZEN", token_version=0)
    db.commit.side_effect = RuntimeError("simulated database failure")

    with pytest.raises(RuntimeError, match="simulated database failure"):
        refresh_tokens.create_refresh_session(db, user)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.rollback.assert_called_once()


def test_rotate_refresh_token_rolls_back_on_unexpected_error():
    db = Mock()
    db.scalar.side_effect = RuntimeError("simulated database failure")

    with pytest.raises(RuntimeError, match="simulated database failure"):
        refresh_tokens.rotate_refresh_token(db, "sample-refresh-token")

    db.rollback.assert_called_once()


def test_revoke_refresh_token_rolls_back_on_database_error():
    db = Mock()
    db.scalar.side_effect = RuntimeError("simulated database failure")

    with pytest.raises(RuntimeError, match="simulated database failure"):
        refresh_tokens.revoke_refresh_token(db, "sample-refresh-token")

    db.rollback.assert_called_once()
