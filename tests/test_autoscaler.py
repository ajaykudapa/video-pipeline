from autoscaler import desired_workers


def test_scales_with_backlog():
    assert desired_workers(ready=0, unacked=0, per_worker=5, min_w=1, max_w=6) == 1
    assert desired_workers(ready=5, unacked=0, per_worker=5, min_w=1, max_w=6) == 1
    assert desired_workers(ready=6, unacked=0, per_worker=5, min_w=1, max_w=6) == 2
    assert desired_workers(ready=20, unacked=5, per_worker=5, min_w=1, max_w=6) == 5


def test_clamped_to_bounds():
    assert desired_workers(ready=1000, unacked=0, per_worker=5, min_w=1, max_w=6) == 6
    assert desired_workers(ready=0, unacked=0, per_worker=5, min_w=2, max_w=6) == 2


def test_unacked_counts_toward_backlog():
    # tasks being processed still occupy capacity
    assert desired_workers(ready=0, unacked=12, per_worker=5, min_w=1, max_w=6) == 3
