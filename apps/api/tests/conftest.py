"""Database fixtures.

Most of the suite is pure and offline. The lifecycle tests are not: expiry,
change logging and source reconciliation are all *stored* facts, and the models
use JSONB and ARRAY columns that no in-memory engine implements, so they need a
real Postgres.

They run against ``settings.test_database_url`` — never the student's own
database — and every test is wrapped in a transaction that is rolled back, so a
run leaves nothing behind. If that database is not reachable the fixture skips
rather than failing, so ``pytest`` on a plane still runs everything else.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Base


@pytest.fixture(scope="session")
def engine():
    url = get_settings().test_database_url
    candidate = create_engine(url, future=True)
    try:
        Base.metadata.create_all(candidate)
    except SQLAlchemyError as exc:
        pytest.skip(f"test database not reachable ({type(exc).__name__}); createdb it to run: {url}")
    return candidate


@pytest.fixture
def db(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, future=True, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
