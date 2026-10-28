"""Basic API tests using an in-memory SQLite database (no Docker required)."""
import os

# Force an isolated, in-memory test database before importing the app.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from fastapi.testclient import TestClient

from app.database import Base, engine, get_db
from app.main import app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)
Base.metadata.create_all(bind=TEST_ENGINE)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)


def test_task_crud_flow():
    create = client.post("/tasks", json={"title": "Test task", "description": "Details"})
    assert create.status_code == 201
    task = create.json()
    assert task["title"] == "Test task"
    assert task["completed"] is False

    task_id = task["id"]
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert any(item["id"] == task_id for item in listed.json())

    updated = client.put(f"/tasks/{task_id}", json={"completed": True})
    assert updated.status_code == 200
    assert updated.json()["completed"] is True

    deleted = client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json()["id"] == task_id
    assert client.get(f"/tasks/{task_id}").status_code == 404


def test_validation_and_stats():
    assert client.post("/tasks", json={"title": ""}).status_code == 422
    client.post("/tasks", json={"title": "Done", "completed": True})
    client.post("/tasks", json={"title": "Pending", "completed": False})
    stats = client.get("/stats").json()
    assert stats["total_tasks"] == 2
    assert stats["completed"] == 1
    assert stats["pending"] == 1
    assert stats["completion_rate"] == 50.0


def test_swagger_and_metrics_routes_exist():
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "todo_api_requests_total" in metrics.text
