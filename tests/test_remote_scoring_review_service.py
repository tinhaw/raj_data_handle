from __future__ import annotations

from datetime import datetime
from io import BytesIO

import httpx
import pytest
from openpyxl import Workbook

from packages.domain.services.remote_scoring_review_service import (
    RemoteScoringReviewError,
    ScoringReviewRemoteClient,
)
from packages.domain.services.scoring_reviewed_cases_import_service import (
    SCORING_REVIEWED_CASES_EXPORT_COLUMNS,
)


def _empty_export_content() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(SCORING_REVIEWED_CASES_EXPORT_COLUMNS)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_reviewed_cases_export_uses_one_excel_download_with_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/external/v1/scoring-reviews/reviewed-cases/export"
        assert request.headers["x-api-key"] == "test-api-key"
        assert request.headers["accept"] == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert request.url.params["create_time"] == (
            '["2026-07-31T00:00:00+05:30","2026-07-31T23:59:59+05:30"]'
        )
        assert request.url.params["sort_by"] == "reviewedAt"
        assert request.url.params["sort_order"] == "desc"
        assert "page" not in request.url.params
        assert "page_size" not in request.url.params
        return httpx.Response(
            200,
            content=b"PK\x03\x04workbook",
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
        )

    client = ScoringReviewRemoteClient(
        base_url="https://scoring.example.test/api",
        api_key="test-api-key",
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        content = await client.export_reviewed_cases(
            create_time_start=datetime.fromisoformat("2026-07-31T00:00:00+05:30"),
            create_time_end=datetime.fromisoformat("2026-07-31T23:59:59+05:30"),
        )
    finally:
        await client._client.aclose()

    assert content == b"PK\x03\x04workbook"


@pytest.mark.asyncio
async def test_reviewed_cases_export_rejects_oversized_workbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "packages.domain.services.remote_scoring_review_service."
        "MAX_SCORING_REVIEWED_CASES_EXPORT_BYTES",
        3,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04")

    client = ScoringReviewRemoteClient(
        base_url="https://scoring.example.test/api",
        api_key="test-api-key",
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RemoteScoringReviewError, match="超过大小限制"):
            await client.export_reviewed_cases()
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_connection_validates_a_low_volume_export_workbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ScoringReviewRemoteClient(
        base_url="https://scoring.example.test/api",
        api_key="test-api-key",
    )
    requested_ranges: list[tuple[datetime | None, datetime | None]] = []

    async def fake_export_reviewed_cases(
        *,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
    ) -> bytes:
        requested_ranges.append((create_time_start, create_time_end))
        return _empty_export_content()

    monkeypatch.setattr(client, "export_reviewed_cases", fake_export_reviewed_cases)
    try:
        await client.test_connection()
    finally:
        await client._client.aclose()

    assert len(requested_ranges) == 1
    start_at, end_at = requested_ranges[0]
    assert start_at is not None
    assert start_at == end_at
    assert start_at.tzinfo is not None


@pytest.mark.asyncio
async def test_connection_rejects_an_invalid_export_workbook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ScoringReviewRemoteClient(
        base_url="https://scoring.example.test/api",
        api_key="test-api-key",
    )

    async def fake_export_reviewed_cases(**_: object) -> bytes:
        return b"not-an-xlsx"

    monkeypatch.setattr(client, "export_reviewed_cases", fake_export_reviewed_cases)
    try:
        with pytest.raises(RemoteScoringReviewError, match="导出文件校验失败"):
            await client.test_connection()
    finally:
        await client._client.aclose()
