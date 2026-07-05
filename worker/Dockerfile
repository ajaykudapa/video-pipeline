# Build context is the repo root (see docker-compose.yml)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY worker/worker/ ./worker/

EXPOSE 9100
CMD ["python", "-m", "worker.main"]
