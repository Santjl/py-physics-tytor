import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "test")

from app.api.deps import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app import models  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if TEST_DATABASE_URL.startswith("sqlite") else {},
    future=True,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture
def admin_user(db_session):
    user = models.User(email="admin@example.com", password_hash=get_password_hash("secret"), role="admin")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def student_user(db_session):
    user = models.User(email="student@example.com", password_hash=get_password_hash("secret"), role="student")
    db_session.add(user)
    db_session.commit()
    return user
