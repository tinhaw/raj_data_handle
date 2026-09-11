from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.domain.services.automatic_refresh_retry import (
    can_retry_failed_automatic_window,
)


def test_failed_automatic_window_retries_only_after_configured_interval() -> None:
    now = datetime(2026, 8, 1, 0, 5, tzinfo=UTC)
    window = datetime(2026, 7, 31, tzinfo=UTC)

    assert not can_retry_failed_automatic_window(
        status="failed",
        previous_window_marker=window,
        automatic_window_marker=window,
        last_failed_at=now,
        automatic_failure_count=1,
        retry_limit=1,
        retry_interval_minutes=5,
        now=now + timedelta(minutes=4, seconds=59),
    )
    assert can_retry_failed_automatic_window(
        status="failed",
        previous_window_marker=window,
        automatic_window_marker=window,
        last_failed_at=now,
        automatic_failure_count=1,
        retry_limit=1,
        retry_interval_minutes=5,
        now=now + timedelta(minutes=5),
    )


def test_retry_limit_counts_only_attempts_after_the_initial_failure() -> None:
    now = datetime(2026, 8, 1, 0, 5, tzinfo=UTC)
    window = datetime(2026, 7, 31, tzinfo=UTC)

    assert not can_retry_failed_automatic_window(
        status="failed",
        previous_window_marker=window,
        automatic_window_marker=window,
        last_failed_at=now,
        automatic_failure_count=1,
        retry_limit=0,
        retry_interval_minutes=1,
        now=now + timedelta(minutes=1),
    )
    assert not can_retry_failed_automatic_window(
        status="failed",
        previous_window_marker=window,
        automatic_window_marker=window,
        last_failed_at=now,
        automatic_failure_count=2,
        retry_limit=1,
        retry_interval_minutes=1,
        now=now + timedelta(minutes=1),
    )
    assert can_retry_failed_automatic_window(
        status="failed",
        previous_window_marker=window,
        automatic_window_marker=window + timedelta(days=1),
        last_failed_at=now,
        automatic_failure_count=2,
        retry_limit=0,
        retry_interval_minutes=1,
        now=now,
    )
