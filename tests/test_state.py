import json

import fakeredis
import pytest

from common import planning, state


@pytest.fixture
def r():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def job(r):
    tasks = planning.plan_tasks("job1", "job1/source.mp4", "vid.mp4")
    state.create_job(r, "job1", "vid.mp4", "job1/source.mp4", tasks)
    return tasks


def test_create_job(r, job):
    j = state.get_job(r, "job1")
    assert j["status"] == "processing"
    assert int(j["total_tasks"]) == 5
    assert len(j["tasks"]) == 5
    assert all(t["status"] == "queued" for t in j["tasks"].values())


def test_finish_all_tasks_completes_job(r, job):
    for t in job:
        state.finish_task(r, "job1", t["task_id"], success=True,
                          output_key="x", attempts=1)
    j = state.get_job(r, "job1")
    assert j["status"] == "completed"
    assert int(j["done_tasks"]) == 5


def test_one_failure_marks_completed_with_errors(r, job):
    state.finish_task(r, "job1", job[0]["task_id"], success=False,
                      error="boom", attempts=4)
    for t in job[1:]:
        state.finish_task(r, "job1", t["task_id"], success=True,
                          output_key="x", attempts=1)
    j = state.get_job(r, "job1")
    assert j["status"] == "completed_with_errors"
    assert j["tasks"][job[0]["task_id"]]["error"] == "boom"


def test_finish_task_publishes_progress_event(r, job):
    ps = r.pubsub()
    ps.subscribe(state.EVENTS_CHANNEL)
    ps.get_message(timeout=1)  # consume subscribe confirmation
    state.finish_task(r, "job1", job[0]["task_id"], success=True,
                      output_key="x", attempts=1)
    msg = ps.get_message(timeout=1)
    event = json.loads(msg["data"])
    assert event["job_id"] == "job1"
    assert event["task_status"] == "done"
    assert event["progress"] == pytest.approx(0.2)


def test_missing_job_returns_none(r):
    assert state.get_job(r, "nope") is None
