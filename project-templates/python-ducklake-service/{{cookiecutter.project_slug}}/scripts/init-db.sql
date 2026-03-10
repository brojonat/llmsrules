-- Create the two PostgreSQL databases used by the application.
-- This script runs automatically via docker-entrypoint-initdb.d.

-- Lake catalog database (stores DuckLake metadata)
CREATE DATABASE "{{cookiecutter.project_slug}}_lake";

-- App database (stores users, sessions, tags, etc.)
CREATE DATABASE "{{cookiecutter.project_slug}}_app";
