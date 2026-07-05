"""Queue-depth-based worker autoscaler.

Polls the RabbitMQ management API; when backlog per worker exceeds the
target, clones a worker container (same image/env/network). Scales down
only after several consecutive low-backlog polls (hysteresis) and only
removes containers it created itself.
"""
from __future__ import annotations

import logging
import math
import os
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("autoscaler")

ROLE_LABEL = "com.videopipeline.role"
CLONE_LABEL = "com.videopipeline.clone"


def desired_workers(ready: int, unacked: int, per_worker: int,
                    min_w: int, max_w: int) -> int:
    """Pure sizing policy: one worker per `per_worker` outstanding tasks."""
    backlog = ready + unacked
    want = math.ceil(backlog / per_worker) if backlog > 0 else min_w
    return max(min_w, min(max_w, want))


def queue_depth(session, base_url: str, queue: str) -> tuple[int, int]:
    r = session.get(f"{base_url}/api/queues/%2f/{queue}", timeout=10)
    r.raise_for_status()
    q = r.json()
    return int(q.get("messages_ready", 0)), int(q.get("messages_unacknowledged", 0))


def worker_containers(client):
    return client.containers.list(filters={"label": f"{ROLE_LABEL}=worker"})


def scale_up(client, template, count: int) -> None:
    net = next(iter(template.attrs["NetworkSettings"]["Networks"]), None)
    for _ in range(count):
        c = client.containers.run(
            template.image.id,
            detach=True,
            environment=template.attrs["Config"]["Env"],
            network=net,
            labels={ROLE_LABEL: "worker", CLONE_LABEL: "true"},
        )
        log.info("scaled up: started %s", c.name)


def scale_down(client, containers, count: int) -> None:
    clones = [c for c in containers if c.labels.get(CLONE_LABEL) == "true"]
    for c in clones[:count]:
        c.stop(timeout=60)  # let in-flight FFmpeg task finish or requeue
        c.remove()
        log.info("scaled down: removed %s", c.name)


def main() -> None:
    import docker
    import requests

    client = docker.from_env()
    session = requests.Session()
    session.auth = (os.environ.get("RABBITMQ_USER", "guest"),
                    os.environ.get("RABBITMQ_PASS", "guest"))

    base_url = os.environ.get("RABBITMQ_MGMT_URL", "http://rabbitmq:15672")
    queue = os.environ.get("QUEUE_NAME", "video_tasks")
    per_worker = int(os.environ.get("TASKS_PER_WORKER", "5"))
    min_w = int(os.environ.get("MIN_WORKERS", "1"))
    max_w = int(os.environ.get("MAX_WORKERS", "6"))
    interval = int(os.environ.get("POLL_INTERVAL_S", "10"))
    grace = int(os.environ.get("SCALE_DOWN_GRACE_POLLS", "3"))

    low_polls = 0
    while True:
        try:
            ready, unacked = queue_depth(session, base_url, queue)
            current = worker_containers(client)
            n = len(current)
            want = desired_workers(ready, unacked, per_worker, min_w, max_w)
            log.info("queue ready=%d unacked=%d workers=%d desired=%d",
                     ready, unacked, n, want)

            if want > n and current:
                low_polls = 0
                scale_up(client, current[0], want - n)
            elif want < n:
                low_polls += 1
                if low_polls >= grace:  # hysteresis: avoid flapping
                    scale_down(client, current, n - want)
                    low_polls = 0
            else:
                low_polls = 0
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            log.warning("poll failed: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
