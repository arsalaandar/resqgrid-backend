import os
from collections.abc import Generator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.dependencies import get_db
from app.main import app


@pytest.fixture(scope="session")
def test_engine():
    database_url = os.getenv("TEST_DATABASE_URL")

    if not database_url:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Configure it to point to resqgrid_test."
        )

    url = make_url(database_url)

    if url.get_backend_name() != "postgresql":
        pytest.fail("Tests must use PostgreSQL.")

    if url.database != "resqgrid_test":
        pytest.fail(
            "Safety check failed: tests may connect only to the resqgrid_test database."
        )

    if url.database == make_url(settings.DATABASE_URL).database:
        pytest.fail("Test database must differ from the application database.")

    engine = create_engine(database_url)

    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        yield engine
    finally:
        engine.dispose()

@pytest_asyncio.fixture
async def auth_client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest.fixture
def db_session(test_engine) -> Generator[Session]:
    connection = test_engine.connect()
    transaction = connection.begin()
    test_session_factory = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )
    session = test_session_factory()

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()

@pytest.fixture(autouse=True)
def reset_rate_limits():
    from app.core.rate_limit import limiter  # adjust to your module path

    limiter.reset()
    yield
    limiter.reset()
