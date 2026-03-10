"""FastAPI application entrypoint."""

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from server.config import check_required_env_vars, get_settings
from server.data import get_connection
from server.data.app_db import get_app_db
from server.log_config import configure_logging, get_logger
from server.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL
from server.routes import api_router, pages_router, tags_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Check required environment variables first
    check_required_env_vars()

    settings = get_settings()

    # Configure logging
    configure_logging(json_format=True, level="INFO")
    log.info("starting_{{cookiecutter.package_name}}", version="0.1.0")

    # Initialize DuckLake connection
    lake = get_connection()
    lake.connect()

    # Initialize app database connection
    app_db = get_app_db()
    app_db.connect()

    # In dev mode, ensure the dev user exists so FK constraints work
    if settings.dev_mode:
        app_db.raw_sql(
            "INSERT INTO users (id, email) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'dev@localhost') "
            "ON CONFLICT (id) DO NOTHING"
        )

    yield

    # Cleanup
    app_db.close()
    lake.close()
    log.info("{{cookiecutter.package_name}}_shutdown")


app = FastAPI(
    title="{{cookiecutter.project_name}}",
    description="{{cookiecutter.description}}",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(api_router)
app.include_router(tags_router)
app.include_router(pages_router)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to track request metrics and add request ID."""
    # Bind request context for logging
    request_id = request.headers.get("x-request-id", "")
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )

    # Track timing
    start = time.perf_counter()

    response: Response = await call_next(request)

    # Record metrics
    duration = time.perf_counter() - start
    path = request.url.path

    # Normalize path for metrics (remove IDs)
    if path.startswith("/entities/") and path != "/entities":
        path = "/entities/{id}"

    HTTP_REQUESTS_TOTAL.labels(
        method=request.method,
        path=path,
        status=response.status_code,
    ).inc()

    HTTP_REQUEST_DURATION.labels(
        method=request.method,
        path=path,
    ).observe(duration)

    # Log request
    log.info(
        "http_request",
        status=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )

    # Clear context
    structlog.contextvars.unbind_contextvars("request_id", "path", "method")

    return response


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
