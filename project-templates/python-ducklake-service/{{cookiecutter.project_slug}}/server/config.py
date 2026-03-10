"""Configuration management using pydantic-settings."""

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingEnvVarError(Exception):
    """Raised when required environment variables are missing."""

    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="{{cookiecutter.package_name_upper}}_",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    dev_mode: bool = False  # Auto-authenticate all requests

    # DuckLake Catalog
    # Supports: local file, PostgreSQL (libpq format), :memory:
    # PostgreSQL example: host=localhost port=5432 dbname=ducklake user=ducklake password=secret
    catalog_dsn: str = "./data/catalog.db"

    # Application database (PostgreSQL, libpq format)
    # Separate from the lake catalog; stores users, sessions, tags, etc.
    app_db_dsn: str = ""

    # S3 Storage (required)
    s3_endpoint: str
    s3_bucket: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr

    # Auth
    jwt_secret: SecretStr = Field(default=SecretStr("change-me-in-production"))
    magic_link_expiry: int = 900  # 15 minutes
    session_expiry: int = 604800  # 7 days

    # Email
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_pass: SecretStr | None = None
    email_from: str = "noreply@{{cookiecutter.project_slug}}.local"

    # DuckDB
    duckdb_memory_limit: str = "4GB"
    duckdb_threads: int = 4

    # DuckLake Encryption
    # When enabled, all Parquet files are encrypted with auto-generated keys
    # Keys are stored in the catalog (PostgreSQL or local file)
    encryption_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Required environment variables (without prefix)
REQUIRED_ENV_VARS = [
    "JWT_SECRET",
    "S3_ENDPOINT",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "APP_DB_DSN",
]

# Insecure default values that should not be used in production
INSECURE_DEFAULTS = {
    "JWT_SECRET": "change-me-in-production",
}


def check_required_env_vars() -> None:
    """Check that all required environment variables are set.

    Raises:
        MissingEnvVarError: If any required env vars are missing or have insecure defaults.
    """
    prefix = "{{cookiecutter.package_name_upper}}_"
    missing = []
    insecure = []

    for var in REQUIRED_ENV_VARS:
        env_name = f"{prefix}{var}"
        value = os.environ.get(env_name)

        if value is None:
            missing.append(env_name)
        elif var in INSECURE_DEFAULTS and value == INSECURE_DEFAULTS[var]:
            insecure.append(env_name)

    errors = []
    if missing:
        errors.append(f"Missing required environment variables: {', '.join(missing)}")
    if insecure:
        errors.append(f"Environment variables with insecure default values: {', '.join(insecure)}")

    if errors:
        raise MissingEnvVarError(
            "\n".join(errors) + "\n\nSee .env.example for required configuration."
        )
