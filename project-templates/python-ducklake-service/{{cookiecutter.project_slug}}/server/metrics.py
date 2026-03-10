"""Prometheus metrics definitions."""

import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

from prometheus_client import Counter, Gauge, Histogram

# HTTP metrics
HTTP_REQUESTS_TOTAL = Counter(
    "{{cookiecutter.package_name}}_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "{{cookiecutter.package_name}}_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Query metrics
QUERY_DURATION = Histogram(
    "{{cookiecutter.package_name}}_query_duration_seconds",
    "DuckDB query duration in seconds",
    ["query_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
)

# Session metrics
ACTIVE_SESSIONS = Gauge(
    "{{cookiecutter.package_name}}_active_sessions",
    "Number of active user sessions",
)


@contextmanager
def track_request(method: str, path: str):
    """Context manager to track HTTP request duration."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(duration)


P = ParamSpec("P")
R = TypeVar("R")


def track_query(query_type: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to track query duration."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.perf_counter() - start
                QUERY_DURATION.labels(query_type=query_type).observe(duration)

        return wrapper

    return decorator
