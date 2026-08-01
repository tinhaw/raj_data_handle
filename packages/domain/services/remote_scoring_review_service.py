"""Strict client for the source-scoped, read-only scoring-review API.

Only an allowlisted projection is materialized.  In particular, names, bank
details, remote request payloads, error reasons, and any unknown future fields
from the external response never leave this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from packages.domain.services.scoring_reviewed_cases_import_service import ScoringReviewedCase

REVIEWED_CASES_PATH = "/external/v1/scoring-reviews/reviewed-cases"
MAX_SCORING_REVIEW_PAGE_SIZE = 500
MAX_SCORING_REVIEW_RESPONSE_BYTES = 8 * 1024 * 1024


class RemoteScoringReviewError(ValueError):
    """Safe failure raised when the external scoring API cannot be consumed."""


@dataclass(frozen=True, slots=True)
class ScoringReviewRemotePage:
    cases: list[ScoringReviewedCase]
    total: int
    page: int
    page_size: int


def _text(value: object, *, limit: int) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set, bool)):
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > limit:
        raise RemoteScoringReviewError("评分审核 API 返回了超长字段。")
    return normalized


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _elapsed(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RemoteScoringReviewError("评分审核 API 返回了无效的耗时字段。")
    if value < 0 or int(value) != value or value > 31_536_000:
        raise RemoteScoringReviewError("评分审核 API 返回了无效的耗时字段。")
    seconds = int(value)
    hours, remainder = divmod(seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _case_from_item(item: object) -> ScoringReviewedCase:
    if not isinstance(item, dict):
        raise RemoteScoringReviewError("评分审核 API 返回了无效案件数据。")
    case_id = _text(item.get("caseId"), limit=120)
    if case_id is None:
        raise RemoteScoringReviewError("评分审核 API 返回了缺少案件号的数据。")
    initial_observation = _object(item.get("initialScoringObservation"))
    scoring_observation = _object(item.get("scoringObservation"))
    scenario_review = _text(
        scoring_observation.get("decisionLabel") or scoring_observation.get("decision"),
        limit=120,
    )
    return ScoringReviewedCase(
        withdraw_order_id=case_id,
        # The list API intentionally does not offer a stable, scalar
        # equivalent of the spreadsheet's global-hard-condition column.
        global_hard_condition=None,
        scenario_review=scenario_review,
        # The contract defines this immutable initial observation as the
        # correct score for attribution; do not use mutable systemScore.
        score_review=_text(initial_observation.get("score"), limit=80),
        decision_stage=_text(scoring_observation.get("reviewStage"), limit=120),
        final_review_suggestion=_text(item.get("systemDecision"), limit=120),
        operation_result=_text(item.get("auditPlatformProcessedLabel"), limit=120),
        review_summary=_text(item.get("summary"), limit=2_000),
        current_status=_text(item.get("queue"), limit=120),
        review_completed_at=_text(item.get("auditFinishedAt"), limit=32),
        review_duration=_elapsed(item.get("auditElapsedSeconds")),
        queue_duration=_elapsed(item.get("queueWaitSeconds")),
        entered_queue_at=_text(item.get("queueEnteredAt"), limit=32),
        exited_queue_at=_text(item.get("queueExitedAt"), limit=32),
    )


class ScoringReviewRemoteClient:
    """Read reviewed cases through one fixed API path and one API-key header."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
        )

    async def __aenter__(self) -> ScoringReviewRemoteClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def _get_json(self, *, params: dict[str, str]) -> dict[str, Any]:
        try:
            async with self._client.stream(
                "GET",
                f"{self.base_url}{REVIEWED_CASES_PATH}",
                headers={"X-API-Key": self._api_key, "Accept": "application/json"},
                params=params,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise RemoteScoringReviewError("评分审核 API 请求未成功。")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_SCORING_REVIEW_RESPONSE_BYTES:
                        raise RemoteScoringReviewError("评分审核 API 响应超过大小限制。")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise RemoteScoringReviewError("评分审核 API 请求失败。") from exc
        try:
            payload = json.loads(b"".join(chunks))
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise RemoteScoringReviewError("评分审核 API 未返回有效 JSON。") from exc
        if not isinstance(payload, dict):
            raise RemoteScoringReviewError("评分审核 API 返回格式无效。")
        return payload

    async def fetch_reviewed_cases(
        self,
        *,
        page: int,
        page_size: int,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
    ) -> ScoringReviewRemotePage:
        if page < 1 or not 1 <= page_size <= MAX_SCORING_REVIEW_PAGE_SIZE:
            raise ValueError("评分审核 API 分页参数无效。")
        if (create_time_start is None) != (create_time_end is None):
            raise ValueError("评分审核 API 创建时间范围必须同时提供开始和结束时间。")
        params = {
            "page": str(page),
            "page_size": str(page_size),
            "sort_by": "reviewedAt",
            "sort_order": "desc",
        }
        if create_time_start is not None and create_time_end is not None:
            params["create_time"] = json.dumps(
                [create_time_start.isoformat(), create_time_end.isoformat()],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        payload = await self._get_json(params=params)
        items = payload.get("items")
        total = payload.get("total")
        returned_page = payload.get("page")
        returned_page_size = payload.get("pageSize")
        if (
            not isinstance(items, list)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or isinstance(returned_page, bool)
            or not isinstance(returned_page, int)
            or returned_page != page
            or isinstance(returned_page_size, bool)
            or not isinstance(returned_page_size, int)
            or not 1 <= returned_page_size <= MAX_SCORING_REVIEW_PAGE_SIZE
            or len(items) > returned_page_size
        ):
            raise RemoteScoringReviewError("评分审核 API 返回的分页数据无效。")
        return ScoringReviewRemotePage(
            cases=[_case_from_item(item) for item in items],
            total=total,
            page=returned_page,
            page_size=returned_page_size,
        )

    async def test_connection(self) -> None:
        await self.fetch_reviewed_cases(page=1, page_size=1)
