FROM python:{{cookiecutter.python_version}}-slim AS builder

RUN pip install uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN uv pip install --system .

FROM python:{{cookiecutter.python_version}}-slim

COPY --from=builder /usr/local/lib/python{{cookiecutter.python_version}}/site-packages /usr/local/lib/python{{cookiecutter.python_version}}/site-packages
COPY --from=builder /usr/local/bin/{{cookiecutter.project_slug}} /usr/local/bin/
COPY server/ server/

EXPOSE 8000

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
