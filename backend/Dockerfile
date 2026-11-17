FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY --link pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --link app app
COPY --link alembic.ini .
COPY --link alembic alembic
RUN mkdir -p /var/log/cv-applier

ENV PORT=8000
ENV LOG_FILE=/var/log/cv-applier/app.log
CMD exec uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips="*"
