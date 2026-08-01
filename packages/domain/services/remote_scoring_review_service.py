"""Bounded client for the source-scoped, read-only scoring-review export API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from packages.domain.services.scoring_reviewed_cases_import_service import (
    MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES,
    ScoringReviewedCasesImportError,
    parse_scoring_reviewed_cases_export,
)

REVIEWED_CASES_EXPORT_PATH = "/external/v1/scoring-reviews/reviewed-cases/export"


class RemoteScoringReviewError(ValueError):
    """Safe failure raised when the external scoring API cannot be consumed."""


class ScoringReviewRemoteClient:
    """Read reviewed cases only through the Excel export contract."""

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

    async def export_reviewed_cases(
        self,
        *,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
    ) -> bytes:
        """Download one bounded reviewed-cases workbook without persisting it.

        Stream into a capped in-memory buffer.  Callers must parse and discard
        the returned bytes rather than write the remote workbook to disk.
        """

        if (create_time_start is None) != (create_time_end is None):
            raise ValueError("评分审核 API 创建时间范围必须同时提供开始和结束时间。")
        params = {
            "sort_by": "reviewedAt",
            "sort_order": "desc",
        }
        if create_time_start is not None and create_time_end is not None:
            params["create_time"] = json.dumps(
                [create_time_start.isoformat(), create_time_end.isoformat()],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        try:
            async with self._client.stream(
                "GET",
                f"{self.base_url}{REVIEWED_CASES_EXPORT_PATH}",
                headers={
                    "X-API-Key": self._api_key,
                    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
                params=params,
                # Workbook generation can take longer than an ordinary API
                # probe; the external export contract calls for 180 seconds.
                timeout=httpx.Timeout(180.0, connect=10.0),
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise RemoteScoringReviewError("评分审核 API 导出请求未成功。")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES:
                        raise RemoteScoringReviewError("评分审核 API 导出文件超过大小限制。")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise RemoteScoringReviewError("评分审核 API 导出请求失败。") from exc
        return b"".join(chunks)

    async def test_connection(self) -> None:
        """Verify the same low-volume export and strict workbook contract.

        A one-instant range avoids downloading historical data while ensuring
        that the configured URL, key, export route, and current workbook schema
        are all usable by the automatic sync.
        """

        probe_at = datetime.now(UTC).replace(microsecond=0)
        content = await self.export_reviewed_cases(
            create_time_start=probe_at,
            create_time_end=probe_at,
        )
        try:
            parse_scoring_reviewed_cases_export(content)
        except ScoringReviewedCasesImportError as exc:
            raise RemoteScoringReviewError("评分审核 API 导出文件校验失败。") from exc
