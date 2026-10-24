# Pike website + account server.
# A tiny, dependency-light Flask app (stdlib SQLite for accounts).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code.
COPY . .

# Accounts live in a single SQLite file. Mount a volume at this path to persist
# them across restarts/redeploys (e.g. Render disk, Fly volume, docker -v).
ENV PIKE_ACCOUNT_DATA=/data
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080
CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 60"]