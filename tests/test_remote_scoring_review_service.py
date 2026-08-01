from __future__ import annotations

import pytest

from packages.domain.services.remote_scoring_review_service import ScoringReviewRemoteClient


@pytest.mark.asyncio
async def test_reviewed_case_projection_uses_initial_score_and_discards_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_json(*_: object, **__: object) -> dict[str, object]:
        return {
            "items": [
                {
                    "caseId": "case-1",
                    "systemScore": 99,
                    "initialScoringObservation": {"auditor": "AIPF3", "score": 35},
                    "scoringObservation": {
                        "decisionLabel": "人工复核",
                        "reviewStage": "评分审核",
                    },
                    "systemDecision": "manual_review",
                    "auditPlatformProcessedLabel": "已处理",
                    "summary": "允许缓存的评分摘要",
                    "queue": "processed",
                    "auditFinishedAt": "2026-07-31 10:01:12",
                    "auditElapsedSeconds": 72.4,
                    "queueWaitSeconds": 8.6,
                    "queueEnteredAt": "2026-07-31 10:00:00",
                    "queueExitedAt": "2026-07-31 10:00:08",
                    "playerName": "must-not-project",
                    "bankAccount": "must-not-project",
                    "remoteRequestData": {"token": "must-not-project"},
                }
            ],
            "total": 1,
            "page": 1,
            "pageSize": 500,
        }

    client = ScoringReviewRemoteClient(
        base_url="https://scoring.example.test/api",
        api_key="secret",
    )
    monkeypatch.setattr(client, "_get_json", fake_get_json)
    try:
        page = await client.fetch_reviewed_cases(page=1, page_size=500)
    finally:
        await client._client.aclose()

    assert page.total == 1
    case = page.cases[0]
    assert case.withdraw_order_id == "case-1"
    assert case.score_review == "35"
    assert case.scenario_review == "人工复核"
    assert case.decision_stage == "评分审核"
    assert case.review_duration == "00:01:12"
    assert case.queue_duration == "00:00:09"
    assert "player_name" not in case.__dataclass_fields__
    assert "bank_account" not in case.__dataclass_fields__
    assert "remote_request_data" not in case.__dataclass_fields__
