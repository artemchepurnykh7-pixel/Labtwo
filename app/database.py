"""Database connection and SQLAlchemy session management."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://todouser:todopass@localhost:5432/todoapp",
)

_engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # StaticPool keeps the in-memory database available across TestClient threads.
    _engine_options["connect_args"] = {"check_same_thread": False}
    if ":memory:" in DATABASE_URL or DATABASE_URL.endswith("sqlite://"):
        _engine_options["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Yield one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
