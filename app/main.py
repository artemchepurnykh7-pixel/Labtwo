"""FastAPI TODO API with PostgreSQL persistence, Redis cache and Prometheus metrics."""
import json
import os
import time
from contextlib import asynccontextmanager
from typing import List

import redis
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import TaskCreate, TaskDB, TaskRead, TaskUpdate

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)

REQUESTS = Counter(
    "todo_api_requests_total",
    "Number of HTTP requests handled by the TODO API",
    ["method", "endpoint", "status"],
)
REQUEST_DURATION = Histogram(
    "todo_api_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)
TASKS_TOTAL = Gauge("todo_tasks_total", "Current number of tasks stored in PostgreSQL")
TASKS_COMPLETED = Gauge("todo_tasks_completed_total", "Current number of completed tasks")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Docker Compose starts the API only after PostgreSQL reports healthy.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="TODO API",
    description="API для управления задачами с PostgreSQL, Redis и метриками Prometheus.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def collect_request_metrics(request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    endpoint = getattr(route, "path", request.url.path)
    REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    REQUEST_DURATION.labels(request.method, endpoint).observe(time.perf_counter() - started_at)
    return response


def get_cache(key: str):
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except (redis.RedisError, json.JSONDecodeError, TypeError):
        return None


def set_cache(key: str, value, ttl: int = CACHE_TTL) -> None:
    try:
        redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except redis.RedisError:
        # The API remains available when the optional cache is unavailable.
        pass


def invalidate_cache() -> None:
    try:
        keys = list(redis_client.scan_iter("tasks:*"))
        if keys:
            redis_client.delete(*keys)
    except redis.RedisError:
        pass


def task_to_dict(task: TaskDB) -> dict:
    return TaskRead.model_validate(task).model_dump()


@app.get("/health", tags=["service"])
async def health_check():
    database_status = "healthy"
    cache_status = "healthy"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unhealthy"
    try:
        redis_client.ping()
    except redis.RedisError:
        cache_status = "unhealthy"

    overall = "healthy" if database_status == "healthy" and cache_status == "healthy" else "degraded"
    result = {
        "status": overall,
        "service": "TODO API",
        "database": database_status,
        "cache": cache_status,
    }
    return Response(
        content=json.dumps(result, ensure_ascii=False),
        media_type="application/json",
        status_code=200 if overall == "healthy" else 503,
    )


@app.get("/tasks", response_model=List[TaskRead], tags=["tasks"])
def get_tasks(db: Session = Depends(get_db)):
    cached = get_cache("tasks:all")
    if cached is not None:
        return cached
    tasks = db.query(TaskDB).order_by(TaskDB.id).all()
    result = [task_to_dict(task) for task in tasks]
    set_cache("tasks:all", result)
    return result


@app.post("/tasks", response_model=TaskRead, status_code=201, tags=["tasks"])
def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    db_task = TaskDB(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    invalidate_cache()
    return task_to_dict(db_task)


@app.get("/tasks/{task_id}", response_model=TaskRead, tags=["tasks"])
def get_task(task_id: int, db: Session = Depends(get_db)):
    cached = get_cache(f"tasks:{task_id}")
    if cached is not None:
        return cached
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    result = task_to_dict(task)
    set_cache(f"tasks:{task_id}", result)
    return result


@app.put("/tasks/{task_id}", response_model=TaskRead, tags=["tasks"])
def update_task(task_id: int, task_update: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = task_update.model_dump(exclude_unset=True)
    if "title" in update_data and update_data["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")
    for field, value in update_data.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    invalidate_cache()
    return task_to_dict(task)


@app.delete("/tasks/{task_id}", tags=["tasks"])
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    invalidate_cache()
    return {"message": "Task deleted successfully", "id": task_id}


@app.get("/stats", tags=["statistics"])
def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(TaskDB.id)).scalar() or 0
    completed = db.query(func.count(TaskDB.id)).filter(TaskDB.completed.is_(True)).scalar() or 0
    pending = total - completed
    return {
        "total_tasks": total,
        "completed": completed,
        "pending": pending,
        "completion_rate": round(completed / total * 100, 2) if total else 0,
    }


@app.get("/metrics", include_in_schema=False)
def metrics(db: Session = Depends(get_db)):
    try:
        total = db.query(func.count(TaskDB.id)).scalar() or 0
        completed = db.query(func.count(TaskDB.id)).filter(TaskDB.completed.is_(True)).scalar() or 0
        TASKS_TOTAL.set(total)
        TASKS_COMPLETED.set(completed)
    except SQLAlchemyError:
        # API request metrics are still available if PostgreSQL is down.
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
