# ruff: noqa: E402
"""FastAPI application for Bayesian experiment management."""

import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager

# Suppress PyMC/Numba warnings
warnings.filterwarnings(
    "ignore",
    message=".*FNV hashing is not implemented in Numba.*",
    category=UserWarning,
    module="numba.cpython.hashing",
)

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from {{cookiecutter.package_name}}.server.routers import experiments


def configure_logging() -> None:
    """Configure structured logging."""
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    json_logs = os.getenv("LOG_JSON", "false").lower() == "true"
    service_name = os.getenv("SERVICE_NAME", "{{cookiecutter.project_slug}}")

    logging.basicConfig(level=log_level, stream=sys.stdout)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(service=service_name)


configure_logging()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    log.info("service.startup")
    try:
        yield
    finally:
        log.info("service.shutdown")


app = FastAPI(
    title="{{cookiecutter.project_name}}",
    description="{{cookiecutter.description}}",
    lifespan=lifespan,
)

# Include routers
app.include_router(experiments.router)

# Prometheus metrics
Instrumentator().instrument(app).expose(app)


@app.get("/healthz", tags=["health"])
def healthz():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("{{cookiecutter.package_name}}.server.main:app", host=host, port=port, reload=False)
