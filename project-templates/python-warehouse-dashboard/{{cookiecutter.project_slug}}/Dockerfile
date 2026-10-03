# One image for every job: `{{cookiecutter.project_slug}} serve` (deploy/run.sh) and the refresh
# (deploy/refresh.sh), whatever runs it: this pod at startup, a sidecar, a
# CronJob, a systemd timer.
#
# No credentials in here: the LLM and litestream keys arrive at runtime from a
# Kubernetes secret generated from .env.prod.
FROM python:3.13-slim

# uv from its official image.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# litestream replicates the app database (feedback, LLM usage) to object storage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && wget -qO- https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz \
       | tar xz -C /usr/local/bin \
    && apt-get purge -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so source edits don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev
COPY deploy/ deploy/

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data \
    APP_DB=/data/app/app.sqlite \
    HOST=0.0.0.0 \
    PORT=8080 \
    LOG_FORMAT=json

EXPOSE 8080
CMD ["/app/deploy/run.sh"]
