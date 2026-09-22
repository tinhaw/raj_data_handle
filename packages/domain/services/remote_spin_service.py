from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from packages.domain.services.remote_charge_service import (
    PLAYER_INFO_LIST_PATH,
    SPIN_ORDER_INDEX_PATH,
    USER_SOURCE_CHANNEL_DICTIONARY_PATH,
    RajAdminChargeClient,
    RemoteResponseError,
    _response_data,
    _text,
)

SPIN_ORDER_STATUS_CODES = ("0", "1", "101", "2", "3")
SPIN_CONFIG_IDS = frozenset({"10001", "10002"})
MAX_SPIN_PAGES_PER_STATUS = 200


@dataclass(frozen=True, slots=True)
class SpinFetchResult:
    orders: list[dict[str, Any]]
    fetched_pages: int
    remote_total: int
    complete: bool
    duplicate_count: int = 0


def _page_info(value: object, *, expected_page: int) -> dict[str, int]:
    if not isinstance(value, dict):
        raise RemoteResponseError("远端转盘订单分页信息无效。")
    try:
        total = int(value.get("total") or 0)
        current_page = int(value.get("currentPage") or expected_page)
        total_page = int(value.get("totalPage") or 0)
    except (TypeError, ValueError) as exc:
        raise RemoteResponseError("远端转盘订单分页数字无效。") from exc
    if total < 0 or total_page < 0 or current_page != expected_page:
        raise RemoteResponseError("远端转盘订单返回页码与请求不一致。")
    if total == 0 and total_page not in (0, 1):
        raise RemoteResponseError("远端转盘订单空分页信息无效。")
    return {"total": total, "current_page": current_page, "total_page": total_page}


def normalize_spin_order(item: dict[str, Any], *, requested_status: str) -> dict[str, Any]:
    """Keep only fields approved for local turntable monitoring."""

    remote_status = _text(item.get("status"))
    if remote_status != requested_status:
        raise RemoteResponseError("远端转盘订单状态与请求条件不一致。")
    remote_order_id = _text(item.get("id"))
    uid = _text(item.get("uid"))
    config_id = _text(item.get("spin_id"))
    if not remote_order_id or not uid or not config_id:
        raise RemoteResponseError("远端转盘订单缺少订单 ID、UID 或转盘配置 ID。")
    if config_id not in SPIN_CONFIG_IDS:
        raise RemoteResponseError("远端转盘订单包含未识别的转盘配置 ID。")
    return {
        "remote_order_id": remote_order_id,
        "uid": uid,
        "vip_level": _text(item.get("vip_level")),
        "agent_total_count": _text(item.get("agent_total_count")),
        "amount": _text(item.get("amount")),
        "spin_config_id": config_id,
        "round_number": _text(item.get("round")),
        "invite_count": _text(item.get("invite_count")),
        "status": remote_status,
        "create_time": _text(item.get("create_time")),
        "audit_time": _text(item.get("audit_time")),
    }


class RajAdminSpinClient(RajAdminChargeClient):
    """Allowlisted, read-only client for turntable orders and source channels."""

    def _spin_params(
        self,
        *,
        page: int,
        status: str,
        create_start: str,
        create_end: str,
    ) -> dict[str, Any]:
        return {
            "page": page,
            "pageSize": self.page_size,
            "statusTab": status,
            "status": status,
            "uid": "",
            "create_time[0]": create_start,
            "create_time[1]": create_end,
            "audit_uid": "",
        }

    async def _fetch_spin_page(
        self,
        *,
        page: int,
        status: str,
        create_start: str,
        create_end: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        payload = await self._get_json(
            SPIN_ORDER_INDEX_PATH,
            params=self._spin_params(
                page=page,
                status=status,
                create_start=create_start,
                create_end=create_end,
            ),
        )
        data = _response_data(payload)
        if not isinstance(data, dict):
            raise RemoteResponseError("远端转盘订单 data 结构无效。")
        items = data.get("items")
        if not isinstance(items, list):
            raise RemoteResponseError("远端转盘订单缺少列表数据。")
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise RemoteResponseError("远端转盘订单包含无效条目。")
            normalized.append(normalize_spin_order(item, requested_status=status))
        return normalized, _page_info(data.get("pageInfo"), expected_page=page)

    async def fetch_spin_orders(
        self,
        *,
        create_start: str,
        create_end: str,
        on_page_fetched: Callable[[], Awaitable[None]] | None = None,
    ) -> SpinFetchResult:
        """Fetch every confirmed status separately and merge by remote ID."""

        by_id: dict[str, tuple[int, dict[str, Any]]] = {}
        fetched_pages = 0
        remote_total = 0
        duplicate_count = 0
        # Pending and suspended values are fetched first.  A concurrent state
        # transition into one of the terminal values fetched later is then
        # deterministically resolved in favour of the terminal record.
        status_order = ("0", "3", "1", "101", "2")
        for rank, status in enumerate(status_order):
            page = 1
            expected_total: int | None = None
            status_rows: list[dict[str, Any]] = []
            while True:
                rows, page_info = await self._fetch_spin_page(
                    page=page,
                    status=status,
                    create_start=create_start,
                    create_end=create_end,
                )
                fetched_pages += 1
                status_rows.extend(rows)
                expected_total = page_info["total"]
                total_page = page_info["total_page"]
                if on_page_fetched is not None:
                    await on_page_fetched()
                if total_page > MAX_SPIN_PAGES_PER_STATUS:
                    raise RemoteResponseError("转盘订单数量过多，请缩小刷新时间范围。")
                if total_page == 0 or page >= total_page:
                    break
                page += 1
            if expected_total is None or len(status_rows) != expected_total:
                raise RemoteResponseError("远端转盘订单累计数量与分页总数不一致。")
            remote_total += expected_total
            for order in status_rows:
                previous = by_id.get(order["remote_order_id"])
                if previous is not None:
                    duplicate_count += 1
                    if previous[0] > rank:
                        continue
                by_id[order["remote_order_id"]] = (rank, order)
        return SpinFetchResult(
            orders=[entry[1] for entry in by_id.values()],
            fetched_pages=fetched_pages,
            remote_total=remote_total,
            complete=True,
            duplicate_count=duplicate_count,
        )

    async def fetch_user_channel(self, *, uid: str) -> str | None:
        """Read exactly one UID and project only its channel_id field."""

        payload = await self._get_json(PLAYER_INFO_LIST_PATH, params={"uid": uid})
        data = _response_data(payload)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise RemoteResponseError("远端用户详情结构无效。")
        items = data["items"]
        page_info = data.get("pageInfo")
        if not isinstance(page_info, dict) or int(page_info.get("total") or 0) != 1:
            raise RemoteResponseError("远端用户详情未返回唯一用户。")
        if len(items) != 1 or not isinstance(items[0], dict):
            raise RemoteResponseError("远端用户详情未返回唯一用户。")
        if _text(items[0].get("uid")) != uid:
            raise RemoteResponseError("远端用户详情 UID 与请求不一致。")
        return _text(items[0].get("channel_id"))

    async def fetch_user_source_channels(self) -> list[dict[str, str]]:
        """Read the remote channel_id-to-label mapping without pagination."""

        data = _response_data(await self._get_json(USER_SOURCE_CHANNEL_DICTIONARY_PATH))
        if not isinstance(data, dict) or not isinstance(data.get("channelList"), dict):
            raise RemoteResponseError("远端渠道来源字典结构无效。")
        normalized: dict[str, str] = {}
        for raw_code, raw_label in data["channelList"].items():
            # The remote dictionary can include ``-`` as its own aggregate
            # pseudo-option.  It must not become a normal user-channel
            # filter, but its presence must not make the whole refresh fail.
            # `_text` intentionally treats ``-`` as missing for order data,
            # so preserve it long enough to explicitly skip it here.
            code = str(raw_code).strip() if raw_code is not None else ""
            label = _text(raw_label)
            if code == "-":
                continue
            if not code or not label:
                raise RemoteResponseError("远端渠道来源字典包含空代码或展示名称。")
            if code in normalized:
                raise RemoteResponseError("远端渠道来源字典包含重复代码。")
            normalized[code] = label
        if not normalized:
            raise RemoteResponseError("远端渠道来源字典为空。")
        return [{"code": code, "label": label} for code, label in sorted(normalized.items())]
