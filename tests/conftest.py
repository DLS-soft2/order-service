from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.database import Base, get_db
from app.main import app

SQLALCHEMY_TEST_URL = "sqlite+pysqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def _mock_kafka():
    """Disable Kafka producer lifecycle and publish_event in all tests."""
    with (
        patch("app.main.start_producer", new_callable=AsyncMock),
        patch("app.main.stop_producer", new_callable=AsyncMock),
        patch("app.service.order_service.publish_event", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture(name="db")
def fixture_db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(name="client")
def fixture_client(db):
    """HTTP test client with the test database injected."""
    original_engine = database.engine
    database.engine = test_engine

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    database.engine = original_engine
    app.dependency_overrides.clear()
