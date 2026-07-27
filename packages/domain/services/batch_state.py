from __future__ import annotations

from dataclasses import dataclass


class InvalidBatchTransition(ValueError):
    pass


TERMINAL_BATCH_STATUSES = {
    "completed",
    "failed",
    "comparison_incomplete",
    "cancelled",
}

CANCELLABLE_BATCH_STATUSES = {
    "queued",
    "validating",
    "fetching_remote",
    "comparing",
    "rechecking",
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "uploaded": {"awaiting_confirmation", "failed"},
    "awaiting_confirmation": {"queued", "failed"},
    "queued": {"validating", "cancelling", "failed"},
    "validating": {"fetching_remote", "cancelling", "failed"},
    "fetching_remote": {
        "comparing",
        "cancelling",
        "failed",
        "comparison_incomplete",
    },
    "comparing": {
        "rechecking",
        "completed",
        "cancelling",
        "failed",
        "comparison_incomplete",
    },
    "rechecking": {
        "completed",
        "cancelling",
        "failed",
        "comparison_incomplete",
    },
    "cancelling": {"cancelled"},
}


@dataclass(frozen=True, slots=True)
class BatchTransition:
    from_status: str
    to_status: str


def ensure_transition(from_status: str, to_status: str) -> BatchTransition:
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise InvalidBatchTransition(f"批次不能从 {from_status} 转换到 {to_status}。")
    return BatchTransition(from_status=from_status, to_status=to_status)
