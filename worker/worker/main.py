"""Worker: consumes tasks from RabbitMQ, runs FFmpeg, writes results to MinIO.

Guarantees:
  - at-least-once delivery (manual acks, prefetch=1)
  - idempotent handling (already-done tasks are acked and skipped)
  - failed tasks retry with escalating backoff, then land in a DLQ
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import tempfile
import time

import redis
from minio import Minio
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from common import messaging, planning, state
from worker import tasks as task_exec

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger(f"worker.{socket.gethostname()}")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2f")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9100"))

TASKS = Counter("worker_tasks_total", "Task outcomes",
                ["task_type", "outcome"])  # success | retried | dead_lettered | skipped
DURATION = Histogram("worker_task_duration_seconds", "Task processing time",
                     ["task_type"],
                     buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600])
JOBS_DONE = Counter("worker_jobs_completed_total", "Jobs reaching terminal state",
                    ["status"])
BUSY = Gauge("worker_busy", "1 while processing a task")

rdb = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def minio_client() -> Minio:
    return Minio(os.environ.get("MINIO_ENDPOINT", "minio:9000"),
                 access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
                 secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
                 secure=False)


def handle(ch, method, _props, body) -> None:
    msg = json.loads(body)
    job_id, task_id = msg["job_id"], msg["task_id"]
    task_type, attempts = msg["task_type"], int(msg.get("attempts", 0))

    # ---- idempotency: at-least-once delivery means duplicates are possible
    existing = state.get_task(rdb, job_id, task_id)
    if existing and existing.get("status") in ("done", "failed"):
        log.info("skip %s (already %s)", task_id, existing["status"])
        TASKS.labels(task_type, "skipped").inc()
        ch.basic_ack(method.delivery_tag)
        return

    attempts += 1
    state.mark_task_running(rdb, job_id, task_id, attempts)
    BUSY.set(1)
    started = time.monotonic()
    work_dir = tempfile.mkdtemp(prefix=f"vp-{job_id}-")
    mc = minio_client()

    try:
        src = os.path.join(work_dir, "source")
        mc.fget_object("raw", msg["source_key"], src)

        out_path, content_type = task_exec.execute(task_type, src, work_dir)

        out_key = planning.output_key(job_id, task_type)
        mc.fput_object("processed", out_key, str(out_path),
                       content_type=content_type)

        elapsed = time.monotonic() - started
        DURATION.labels(task_type).observe(elapsed)
        TASKS.labels(task_type, "success").inc()
        job = state.finish_task(rdb, job_id, task_id, success=True,
                                output_key=out_key, attempts=attempts)
        log.info("done %s in %.1fs (attempt %d)", task_id, elapsed, attempts)
        _maybe_count_job(job)
        ch.basic_ack(method.delivery_tag)

    except Exception as exc:  # noqa: BLE001 - any failure follows retry policy
        log.warning("failed %s (attempt %d): %s", task_id, attempts, exc)
        retry_suffix = planning.next_retry_queue(attempts)
        msg["attempts"] = attempts

        if retry_suffix is not None:
            messaging.publish(ch, messaging.retry_queue_name(retry_suffix), msg)
            TASKS.labels(task_type, "retried").inc()
            t = state.get_task(rdb, job_id, task_id)
            if t:
                t.update(status="queued", attempts=attempts, error=str(exc)[:300])
                state.set_task(rdb, job_id, task_id, t)
        else:
            messaging.publish(ch, messaging.DLQ, msg)
            TASKS.labels(task_type, "dead_lettered").inc()
            job = state.finish_task(rdb, job_id, task_id, success=False,
                                    error=str(exc)[:300], attempts=attempts)
            _maybe_count_job(job)

        ch.basic_ack(method.delivery_tag)  # original consumed either way

    finally:
        BUSY.set(0)
        shutil.rmtree(work_dir, ignore_errors=True)


def _maybe_count_job(job: dict) -> None:
    if job.get("status", "").startswith("completed"):
        JOBS_DONE.labels(job["status"]).inc()


def main() -> None:
    start_http_server(METRICS_PORT)
    while True:  # reconnect loop
        try:
            conn = messaging.connect(RABBITMQ_URL)
            ch = conn.channel()
            messaging.declare_topology(ch)
            ch.basic_qos(prefetch_count=1)  # fair dispatch across workers
            ch.basic_consume(queue=messaging.MAIN_QUEUE,
                             on_message_callback=handle)
            log.info("consuming from %s", messaging.MAIN_QUEUE)
            ch.start_consuming()
        except Exception as exc:  # noqa: BLE001
            log.warning("broker connection lost (%s); retrying in 3s", exc)
            time.sleep(3)


if __name__ == "__main__":
    main()
