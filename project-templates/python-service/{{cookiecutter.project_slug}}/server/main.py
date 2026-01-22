import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Dict

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from prometheus_fastapi_instrumentator import Instrumentator


# -------------------------
# Logging configuration
# -------------------------
def configure_logging() -> None:
    log_level_name = os.getenv("LOG_LEVEL", "WARNING").upper()
    log_level = getattr(logging, log_level_name, logging.WARNING)
    json_logs = os.getenv("LOG_JSON", "true").lower() == "true"
    service_name = os.getenv("SERVICE_NAME", "{{cookiecutter.project_slug}}")

    logging.basicConfig(level=log_level, stream=sys.stderr)

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


# -------------------------
# Auth configuration
# -------------------------
JWT_SECRET = os.getenv("AUTH_SECRET", "change-me")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
security = HTTPBearer(auto_error=True)


def require_claims(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict:
    token = credentials.credentials
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


# -------------------------
# App & instrumentation
# -------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
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

Instrumentator().instrument(app).expose(app)


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


@app.get("/whoami", tags=["auth"])
def whoami(claims: Dict = Depends(require_claims)):
    return {"claims": claims}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server.main:app", host=host, port=port, reload=False)
