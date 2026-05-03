"""Pytest fixtures for the ERP test suite.

We use a fresh in-memory SQLite database per test, so tests are fully
isolated and require no clean-up between runs.
"""
import os
import sys
from pathlib import Path
from typing import Generator

# Ensure project root is on sys.path so `import app` works
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force test config BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AI_TM_MOCK_MODE"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import database as db_module
from app.core.auth import hash_password
from app.core.auth_models import User
from app.core.database import Base, get_db
from app.main import app


# ==================================================================
# Engine + per-test session
# ==================================================================
@pytest.fixture(scope="function")
def engine():
    """Fresh in-memory SQLite engine per test, with all tables created."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # share single connection within a test
    )

    # Import all models so metadata is populated
    from app.modules.mdm import models                # noqa: F401
    from app.modules.sd import models                 # noqa: F401
    from app.modules.pp import models                 # noqa: F401
    from app.modules.pp import execution_models       # noqa: F401
    from app.modules.mm import models                 # noqa: F401
    from app.core import auth_models                  # noqa: F401
    from app.core import numbering                    # noqa: F401

    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """Per-test Session bound to the test engine."""
    Session_ = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session_()
    try:
        yield session
    finally:
        session.close()


# ==================================================================
# Admin user + JWT token
# ==================================================================
@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Create an admin user in the test DB."""
    user = User(
        email="test-admin@example.com",
        hashed_password=hash_password("test-password"),
        full_name="Test Admin",
        is_active=True,
        is_superuser=True,
        client_id="DEMO",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_token(admin_user: User) -> str:
    """JWT bearer token for the test admin."""
    from app.core.auth import create_access_token
    return create_access_token(
        subject=admin_user.email, client_id=admin_user.client_id,
    )


# ==================================================================
# FastAPI TestClient with overridden DB dependency
# ==================================================================
@pytest.fixture
def client(engine, db_session) -> Generator[TestClient, None, None]:
    """TestClient that uses the same in-memory DB as the test."""
    Session_ = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_db_override():
        # Use a new session per request, but bound to the same engine
        s = Session_()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}
