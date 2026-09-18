from __future__ import annotations

from datetime import datetime, timedelta


def can_retry_failed_automatic_window(
    *,
    status: str,
    previous_window_marker: datetime | None,
    automatic_window_marker: datetime,
    last_failed_at: datetime | None,
    automatic_failure_count: int,
    retry_limit: int,
    retry_interval_minutes: int,
    now: datetime,
) -> bool:
    """Return whether an automatic refresh may retry its failed window.

    ``retry_limit`` counts only retries after the initial automatic attempt.
    Thus a failure counter of one (the initial failed attempt) is eligible for
    the first retry when the limit is at least one.
    """

    if status != "failed" or previous_window_marker != automatic_window_marker:
        return True
    if automatic_failure_count > retry_limit:
        return False
    return last_failed_at is None or now >= last_failed_at + timedelta(
        minutes=retry_interval_minutes
    )
