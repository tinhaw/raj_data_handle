import pytest

from packages.domain.services.batch_state import (
    InvalidBatchTransition,
    ensure_transition,
)


def test_batch_state_allows_happy_path() -> None:
    path = [
        "awaiting_confirmation",
        "queued",
        "validating",
        "fetching_remote",
        "comparing",
        "rechecking",
        "completed",
    ]
    for from_status, to_status in zip(path, path[1:], strict=False):
        transition = ensure_transition(from_status, to_status)
        assert transition.from_status == from_status
        assert transition.to_status == to_status


def test_terminal_state_cannot_be_changed() -> None:
    with pytest.raises(InvalidBatchTransition):
        ensure_transition("completed", "cancelled")


def test_cancellation_uses_cooperative_intermediate_state() -> None:
    ensure_transition("fetching_remote", "cancelling")
    ensure_transition("cancelling", "cancelled")
