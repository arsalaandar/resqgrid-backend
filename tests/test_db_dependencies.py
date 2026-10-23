"""Edge-case tests for the SQLAlchemy database dependency."""

from unittest.mock import Mock

import pytest

from app.db import dependencies


def test_get_db_yields_created_session_and_closes_it(monkeypatch):
    session = Mock()
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: session)

    generator = dependencies.get_db()

    yielded_session = next(generator)
    assert yielded_session is session
    session.close.assert_not_called()

    with pytest.raises(StopIteration):
        next(generator)

    session.close.assert_called_once_with()


def test_get_db_closes_session_when_consumer_raises(monkeypatch):
    session = Mock()
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: session)

    generator = dependencies.get_db()
    assert next(generator) is session

    with pytest.raises(RuntimeError, match="request handling failed"):
        generator.throw(RuntimeError("request handling failed"))

    session.close.assert_called_once_with()


def test_get_db_closes_session_if_generator_is_closed(monkeypatch):
    session = Mock()
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: session)

    generator = dependencies.get_db()
    assert next(generator) is session

    generator.close()

    session.close.assert_called_once_with()


def test_get_db_does_not_swallow_session_close_error(monkeypatch):
    session = Mock()
    session.close.side_effect = RuntimeError("close failed")
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: session)

    generator = dependencies.get_db()
    assert next(generator) is session

    with pytest.raises(RuntimeError, match="close failed"):
        next(generator)

    session.close.assert_called_once_with()


def test_get_db_session_factory_error_propagates(monkeypatch):
    def fail_to_create_session():
        raise RuntimeError("session creation failed")

    monkeypatch.setattr(dependencies, "SessionLocal", fail_to_create_session)

    with pytest.raises(RuntimeError, match="session creation failed"):
        next(dependencies.get_db())
