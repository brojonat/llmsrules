"""Test fixtures."""

import os

# Set required env vars for testing before importing app
os.environ.setdefault("{{cookiecutter.package_name_upper}}_JWT_SECRET", "test-secret")
os.environ.setdefault("{{cookiecutter.package_name_upper}}_S3_ENDPOINT", "localhost:9000")
os.environ.setdefault("{{cookiecutter.package_name_upper}}_S3_BUCKET", "test-bucket")
os.environ.setdefault("{{cookiecutter.package_name_upper}}_S3_ACCESS_KEY", "minioadmin")
os.environ.setdefault("{{cookiecutter.package_name_upper}}_S3_SECRET_KEY", "minioadmin")
os.environ.setdefault(
    "{{cookiecutter.package_name_upper}}_APP_DB_DSN",
    "host=localhost dbname=test user=postgres password=postgres",
)
os.environ.setdefault("{{cookiecutter.package_name_upper}}_DEV_MODE", "true")
