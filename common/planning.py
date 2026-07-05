"""Pure domain logic: task planning, retry policy, progress math.

Kept free of I/O so it is trivially unit-testable.
"""
from __future__ import annotations

import uuid

# Task types produced for every uploaded video.
TASK_TYPES = [
    "transcode_1080p",
    "transcode_720p",
    "thumbnail",
    "preview_clip",
    "metadata",
]

# attempt number (1-based, after a failure) -> retry queue suffix.
# Escalating TTLs give exponential-ish backoff without per-message TTL
# head-of-line blocking.
RETRY_SCHEDULE = {1: "10s", 2: "30s", 3: "60s"}
MAX_ATTEMPTS = 1 + len(RETRY_SCHEDULE)  # 1 initial try + 3 retries


def plan_tasks(job_id: str, source_key: str, filename: str) -> list[dict]:
    """Split one uploaded video into independent processing tasks."""
    return [
        {
            "job_id": job_id,
            "task_id": f"{job_id}:{t}",
            "task_type": t,
            "source_key": source_key,
            "filename": filename,
            "attempts": 0,
        }
        for t in TASK_TYPES
    ]


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def next_retry_queue(attempts: int) -> str | None:
    """Given the number of attempts already made, return the retry queue
    suffix to use, or None if the task should go to the DLQ."""
    return RETRY_SCHEDULE.get(attempts)


def output_key(job_id: str, task_type: str) -> str:
    ext = {
        "transcode_1080p": "1080p.mp4",
        "transcode_720p": "720p.mp4",
        "thumbnail": "thumbnail.jpg",
        "preview_clip": "preview.mp4",
        "metadata": "metadata.json",
    }[task_type]
    return f"{job_id}/{ext}"


def progress(done: int, failed: int, total: int) -> float:
    """Fraction of tasks in a terminal state, 0.0-1.0."""
    if total <= 0:
        return 0.0
    return min(1.0, (done + failed) / total)


def job_status(done: int, failed: int, total: int) -> str:
    if done + failed < total:
        return "processing"
    return "completed" if failed == 0 else "completed_with_errors"
