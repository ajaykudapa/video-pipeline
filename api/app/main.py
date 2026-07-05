"""API service: uploads, job tracking, SSE progress, static UI."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib

import redis as redis_sync
import redis.asyncio as redis_async
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from prometheus_client import Counter, Histogram, make_asgi_app

from app import storage
from common import messaging, planning, state

app = FastAPI(title="Distributed Video Processing Platform")
app.mount("/metrics", make_asgi_app())

STATIC_DIR = pathlib.Path(__file__).parent / "static"

UPLOADS = Counter("api_uploads_total", "Videos uploaded")
UPLOAD_BYTES = Histogram(
    "api_upload_bytes", "Uploaded file size",
    buckets=[1e6, 1e7, 5e7, 1e8, 5e8, 1e9, 5e9],
)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2f")

rdb = redis_sync.Redis.from_url(REDIS_URL, decode_responses=True)
ardb = redis_async.Redis.from_url(REDIS_URL, decode_responses=True)

_ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


# ---------------------------------------------------------------- publishing
class Publisher:
    """Lazy RabbitMQ channel with one reconnect retry."""

    def __init__(self, url: str):
        self.url = url
        self._conn = None
        self._ch = None

    def _channel(self):
        if self._conn is None or self._conn.is_closed:
            self._conn = messaging.connect(self.url)
            self._ch = self._conn.channel()
            messaging.declare_topology(self._ch)
        return self._ch

    def publish(self, queue: str, message: dict) -> None:
        try:
            messaging.publish(self._channel(), queue, message)
        except Exception:
            self._conn = None  # force reconnect once
            messaging.publish(self._channel(), queue, message)


publisher = Publisher(RABBITMQ_URL)


# -------------------------------------------------------------------- routes
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/videos", status_code=201)
def upload_video(file: UploadFile = File(...)):
    ext = pathlib.Path(file.filename or "video.mp4").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type '{ext}'")

    job_id = planning.new_job_id()
    source_key = f"{job_id}/source{ext}"

    # Streaming multipart upload straight from the request body to MinIO.
    storage.upload_stream(storage.internal(), storage.RAW_BUCKET,
                          source_key, file.file,
                          content_type=file.content_type or "video/mp4")

    size = file.size or 0
    UPLOADS.inc()
    if size:
        UPLOAD_BYTES.observe(size)

    tasks = planning.plan_tasks(job_id, source_key, file.filename or "video")
    state.create_job(rdb, job_id, file.filename or "video", source_key, tasks)
    for t in tasks:
        publisher.publish(messaging.MAIN_QUEUE, t)

    return {"job_id": job_id, "tasks": len(tasks), "source_key": source_key}


@app.get("/api/jobs")
def jobs():
    return state.list_jobs(rdb)


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    job = state.get_job(rdb, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    signer = storage.public()
    job["source_url"] = storage.presign(signer, storage.RAW_BUCKET, job["source_key"])
    for task in job["tasks"].values():
        if task.get("status") == "done" and task.get("output_key"):
            task["download_url"] = storage.presign(
                signer, storage.PROCESSED_BUCKET, task["output_key"])
    return job


@app.get("/api/events")
async def events():
    """Server-Sent Events stream of task/job progress."""
    async def gen():
        pubsub = ardb.pubsub()
        await pubsub.subscribe(state.EVENTS_CHANNEL)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=15.0)
                if msg is None:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {msg['data']}\n\n"
        finally:
            await pubsub.unsubscribe(state.EVENTS_CHANNEL)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/healthz")
def healthz():
    rdb.ping()
    return {"ok": True}
