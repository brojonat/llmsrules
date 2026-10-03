# One image for every container in the pod: `{{cookiecutter.project_slug}} db | feed | sample | serve`.
#
# jax[cuda13] ships CUDA as pip wheels, so no CUDA base image: the node only
# needs an NVIDIA driver and the device plugin (nvidia.com/gpu). The wheels
# make this a multi-GB image; every container shares it, so it's pulled once.
# No credentials in here: they arrive from a Secret generated from .env.prod.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so source edits don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra gpu --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev --extra gpu

ENV PATH="/app/.venv/bin:$PATH" \
    BELT_DB=/data/belt.duckdb \
    JAX_COMPILATION_CACHE_DIR=/data/jax-cache \
    JAX_PERSISTENT_CACHE_MIN_COMPILE_TIME_SECS=0 \
    XLA_PYTHON_CLIENT_PREALLOCATE=false \
    QUACK_URL=quack:localhost \
    HOST=0.0.0.0 \
    PORT=8080

EXPOSE 8080
# The pod's containers pick the subcommand with `args` (db, feed, sample, serve).
ENTRYPOINT ["{{cookiecutter.project_slug}}"]
CMD ["serve"]
