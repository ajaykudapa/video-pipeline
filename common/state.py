"""Job/task state in Redis + progress events on a pub/sub channel.

Keys:
  job:{id}         hash  (id, filename, source_key, status, created_at,
                          total_tasks, done_tasks, failed_tasks)
  job:{id}:tasks   hash  task_id -> JSON blob
  jobs:index       zset  job ids scored by created_at
Channel:
  job-events       JSON progress events consumed by the API's SSE endpoint
"""
from __future__ import annotations

import json
import time

from common import planning

EVENTS_CHANNEL = "job-events"


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


def tasks_key(job_id: str) -> str:
    return f"job:{job_id}:tasks"


def create_job(r, job_id: str, filename: str, source_key: str, tasks: list[dict]) -> None:
    now = time.time()
    pipe = r.pipeline()
    pipe.hset(job_key(job_id), mapping={
        "id": job_id,
        "filename": filename,
        "source_key": source_key,
        "status": "processing",
        "created_at": now,
        "total_tasks": len(tasks),
        "done_tasks": 0,
        "failed_tasks": 0,
    })
    pipe.hset(tasks_key(job_id), mapping={
        t["task_id"]: json.dumps({
            "type": t["task_type"], "status": "queued",
            "attempts": 0, "output_key": None, "error": None,
        })
        for t in tasks
    })
    pipe.zadd("jobs:index", {job_id: now})
    pipe.execute()


def get_task(r, job_id: str, task_id: str) -> dict | None:
    raw = r.hget(tasks_key(job_id), task_id)
    return json.loads(raw) if raw else None


def set_task(r, job_id: str, task_id: str, task: dict) -> None:
    r.hset(tasks_key(job_id), task_id, json.dumps(task))


def finish_task(r, job_id: str, task_id: str, *, success: bool,
                output_key: str | None = None, error: str | None = None,
                attempts: int = 0) -> dict:
    """Mark a task terminal, update job counters, publish a progress event.
    Returns the updated job hash."""
    task = get_task(r, job_id, task_id) or {"type": task_id.split(":")[-1]}
    task.update({
        "status": "done" if success else "failed",
        "output_key": output_key,
        "error": error,
        "attempts": attempts,
    })
    set_task(r, job_id, task_id, task)

    field = "done_tasks" if success else "failed_tasks"
    r.hincrby(job_key(job_id), field, 1)

    job = {k: v for k, v in r.hgetall(job_key(job_id)).items()}
    done = int(job.get("done_tasks", 0))
    failed = int(job.get("failed_tasks", 0))
    total = int(job.get("total_tasks", 0))
    status = planning.job_status(done, failed, total)
    r.hset(job_key(job_id), "status", status)
    job["status"] = status

    publish_event(r, {
        "job_id": job_id,
        "task_id": task_id,
        "task_type": task["type"],
        "task_status": task["status"],
        "job_status": status,
        "progress": planning.progress(done, failed, total),
    })
    return job


def mark_task_running(r, job_id: str, task_id: str, attempts: int) -> None:
    task = get_task(r, job_id, task_id)
    if task:
        task["status"] = "running"
        task["attempts"] = attempts
        set_task(r, job_id, task_id, task)
    publish_event(r, {"job_id": job_id, "task_id": task_id,
                      "task_type": (task or {}).get("type"),
                      "task_status": "running", "job_status": "processing",
                      "progress": None})


def publish_event(r, event: dict) -> None:
    r.publish(EVENTS_CHANNEL, json.dumps(event))


def get_job(r, job_id: str) -> dict | None:
    job = r.hgetall(job_key(job_id))
    if not job:
        return None
    tasks = {tid: json.loads(blob) for tid, blob in r.hgetall(tasks_key(job_id)).items()}
    job["tasks"] = tasks
    return job


def list_jobs(r, limit: int = 50) -> list[dict]:
    ids = r.zrevrange("jobs:index", 0, limit - 1)
    return [j for j in (get_job(r, jid) for jid in ids) if j]
