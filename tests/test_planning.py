from common import planning


def test_plan_tasks_one_per_type():
    tasks = planning.plan_tasks("abc123", "abc123/source.mp4", "cat.mp4")
    assert len(tasks) == len(planning.TASK_TYPES)
    assert {t["task_type"] for t in tasks} == set(planning.TASK_TYPES)
    for t in tasks:
        assert t["task_id"] == f"abc123:{t['task_type']}"
        assert t["attempts"] == 0
        assert t["source_key"] == "abc123/source.mp4"


def test_retry_schedule_escalates_then_dead_letters():
    assert planning.next_retry_queue(1) == "10s"
    assert planning.next_retry_queue(2) == "30s"
    assert planning.next_retry_queue(3) == "60s"
    assert planning.next_retry_queue(4) is None  # -> DLQ
    assert planning.MAX_ATTEMPTS == 4


def test_progress_math():
    assert planning.progress(0, 0, 5) == 0.0
    assert planning.progress(2, 1, 5) == 0.6
    assert planning.progress(5, 0, 5) == 1.0
    assert planning.progress(0, 0, 0) == 0.0  # no divide-by-zero


def test_job_status():
    assert planning.job_status(2, 0, 5) == "processing"
    assert planning.job_status(5, 0, 5) == "completed"
    assert planning.job_status(4, 1, 5) == "completed_with_errors"


def test_output_keys_are_namespaced_by_job():
    assert planning.output_key("j1", "thumbnail") == "j1/thumbnail.jpg"
    assert planning.output_key("j1", "transcode_720p") == "j1/720p.mp4"
    assert planning.output_key("j1", "metadata") == "j1/metadata.json"
