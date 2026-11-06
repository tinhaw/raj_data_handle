"""Strict, bounded read-only pagination; no guessed date/sort/UID filters."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import ceil
from zoneinfo import ZoneInfo

from packages.domain.services.erp_redemption_remote_http_adapter import (
    ErpRedemptionRemoteHttpError,
    ErpRemoteAccountReadGrant,
    RajAdminGiftCodeAdapter,
)

CLAIMS_PATH = "/api/common/userGift/index"
MAX_RECORDS = 200_000


class ClaimReadError(ValueError):
    pass


@dataclass(frozen=True)
class ClaimSnapshot:
    records: list[dict]
    pages: int


def _number(value: object) -> int:
    if isinstance(value, bool) or not str(value).isdigit():
        raise ClaimReadError("远端领取分页信息无效。")
    return int(str(value))


def _text(value: object, limit: int) -> str:
    if value is None or isinstance(value, bool):
        raise ClaimReadError("远端领取记录缺少必要字段。")
    result = str(value).strip()
    if not result or len(result) > limit or any(ord(c) < 32 for c in result):
        raise ClaimReadError("远端领取记录包含无效字段。")
    return result


def parse_record(item: object, group_key: str, timezone_name: str) -> dict:
    if not isinstance(item, dict) or item.get("group_key") != group_key:
        raise ClaimReadError("远端领取记录的兑换码组不匹配。")
    raw_time = _text(item.get("receive_time"), 40)
    try:
        wall = datetime.fromisoformat(raw_time)
        zoned = wall.replace(tzinfo=ZoneInfo(timezone_name)) if wall.tzinfo is None else wall
        business_date = zoned.astimezone(ZoneInfo(timezone_name)).date()
        amount = Decimal(str(item["amount"]))
        if not amount.is_finite() or amount < 0 or amount >= Decimal("1e16"):
            raise ValueError
    except (KeyError, ValueError, InvalidOperation) as exc:
        raise ClaimReadError("远端领取时间或金额无效。") from exc
    return {
        "remote_id": _text(item.get("id"), 100),
        "code": _text(item.get("key"), 255),
        "uid": _text(item.get("uid"), 100),
        "receive_time": raw_time,
        "received_at": zoned.astimezone(UTC),
        "claim_date": business_date,
        "amount": amount,
        "gift_type": _number(item.get("gift_type")),
    }


async def fetch_claim_snapshot(
    adapter: RajAdminGiftCodeAdapter,
    grant: ErpRemoteAccountReadGrant,
    group_key: str,
    timezone_name: str,
    heartbeat: Callable[[], Awaitable[None]],
) -> ClaimSnapshot:
    adapter._assert_read_grant(grant, "CLAIMS")
    fetched_pages = 0

    async def page(number: int, size: int) -> tuple[list, dict]:
        nonlocal fetched_pages
        await heartbeat()
        body, _ = await adapter._request(
            "GET",
            CLAIMS_PATH,
            params={
                "page": number,
                "pageSize": size,
                "group_key": group_key,
                "export_type": "view",
            },
        )
        fetched_pages += 1
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise ClaimReadError("远端领取列表响应无效。")
        data = body["data"]
        items, info = data.get("items"), data.get("pageInfo")
        if not isinstance(items, list) or not isinstance(info, dict):
            raise ClaimReadError("远端领取列表缺少分页信息。")
        if _number(info.get("currentPage")) != number:
            raise ClaimReadError("远端领取列表返回了错误页码。")
        return items, info

    last_error = "远端领取记录未能完整核对。"
    # A rejected page size falls back from page 1. Network/authorization errors
    # are never hidden by blindly trying another page size.
    for size in (100, 50, 30, 20, 10):
        for _attempt in range(2):
            try:
                first, info = await page(1, size)
                total = _number(info.get("total"))
                pages = _number(info.get("totalPage"))
                if total > MAX_RECORDS or pages > MAX_RECORDS or pages < 0:
                    raise ClaimReadError("领取记录超过单轮保护上限，需分批处理。")
                if total == 0:
                    if first or pages not in (0, 1):
                        raise ClaimReadError("空领取列表的分页信息不一致。")
                    return ClaimSnapshot([], fetched_pages)
                if not first or pages < 1 or len(first) > size:
                    raise ClaimReadError("远端领取分页大小或总页数异常。")
                # Detect silent page-size caps from the actual pagination.
                effective_size = len(first) if pages > 1 else size
                if pages != ceil(total / effective_size):
                    raise ClaimReadError("远端领取分页大小被限制或分页信息不一致。")
                records: dict[str, dict] = {}
                for current in range(1, pages + 1):
                    items, current_info = (
                        (first, info) if current == 1 else await page(current, size)
                    )
                    if (
                        _number(current_info.get("total")) != total
                        or _number(current_info.get("totalPage")) != pages
                        or (current < pages and len(items) != effective_size)
                        or not items
                    ):
                        raise ClaimReadError("分页期间领取记录发生变化或未取全，请重试。")
                    for item in items:
                        record = parse_record(item, group_key, timezone_name)
                        previous = records.get(record["remote_id"])
                        if previous is not None and previous != record:
                            raise ClaimReadError("分页中同一领取记录内容不一致。")
                        records[record["remote_id"]] = record
                if len(records) != total:
                    raise ClaimReadError("领取记录去重后数量与远端总数不一致。")
                if pages > 1:
                    check, check_info = await page(1, size)
                    if _number(check_info.get("total")) != total or check != first:
                        raise ClaimReadError("领取列表在抓取期间变化，请稍后重试。")
                return ClaimSnapshot(list(records.values()), fetched_pages)
            except ClaimReadError as exc:
                last_error = str(exc)
                if "保护上限" in last_error:
                    raise
            except ErpRedemptionRemoteHttpError as exc:
                if "HTTP 400" not in str(exc) and "HTTP 422" not in str(exc):
                    raise
                last_error = "远端不接受请求的领取分页大小。"
                break
    raise ClaimReadError(last_error)
