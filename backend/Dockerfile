FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY alembic.ini .
COPY alembic alembic
RUN mkdir -p /var/log/cv-applier

ENV PORT=8000
ENV LOG_FILE=/var/log/cv-applier/app.log
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} \
    --proxy-headers --forwarded-allow-ips="*"
