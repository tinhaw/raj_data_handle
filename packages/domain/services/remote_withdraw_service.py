from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.domain.services.remote_charge_service import (
    WITHDRAW_ORDER_INDEX_PATH,
    WITHDRAW_STATUS_DICTIONARY_PATH,
    RajAdminChargeClient,
    RemoteResponseError,
    _response_data,
)

MAX_WITHDRAW_PAGES = 200


@dataclass(frozen=True, slots=True)
class WithdrawFetchResult:
    orders: list[dict[str, Any]]
    fetched_pages: int
    remote_total: int
    complete: bool


def _text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized and normalized != "-" else None


def _amount(value: object) -> str | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return format(Decimal(normalized), "f")
    except (InvalidOperation, ValueError):
        return None


def normalize_withdraw_order(item: dict[str, Any]) -> dict[str, Any]:
    """Return only fields approved for the withdrawal monitoring page."""

    time_data = item.get("time")
    if not isinstance(time_data, dict):
        time_data = {}
    return {
        "id": _text(item.get("id")) or "",
        "uid": _text(item.get("uid")) or "",
        "amount": _amount(item.get("amount")),
        "real_amount": _amount(item.get("real_amount")),
        "create_time": _text(time_data.get("create_time") or item.get("create_time")),
        "update_time": _text(time_data.get("update_time") or item.get("update_time")),
        "submit_time": _text(item.get("submit_time") or time_data.get("submit_time")),
        "audit_admin": _text(item.get("audit_admin")),
        "status": _text(item.get("status")) or "",
    }


class RajAdminWithdrawClient(RajAdminChargeClient):
    async def fetch_withdraw_statuses(self) -> list[dict[str, str]]:
        """Fetch the fixed remote withdrawal-status dictionary through the read allowlist."""

        data = _response_data(
            await self._get_json(
                WITHDRAW_STATUS_DICTIONARY_PATH,
                params={"code": "withdraw_status"},
            )
        )
        if not isinstance(data, list):
            raise RemoteResponseError("远端提现状态字典结构无效。")

        statuses_by_code: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                raise RemoteResponseError("远端提现状态字典包含无效条目。")
            code = _text(item.get("key"))
            label = _text(item.get("title"))
            if not code or not label:
                raise RemoteResponseError("远端提现状态字典缺少状态值或展示文案。")
            previous = statuses_by_code.get(code)
            if previous is not None and previous != label:
                raise RemoteResponseError("远端提现状态字典中同一状态值对应多个文案。")
            statuses_by_code[code] = label
        if not statuses_by_code:
            raise RemoteResponseError("远端提现状态字典为空。")
        return [
            {"code": code, "label": label}
            for code, label in sorted(statuses_by_code.items())
        ]

    def _withdraw_body(
        self,
        *,
        page: int,
        create_start: str,
        create_end: str,
        uid: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        return {
            "page": page,
            "pageSize": self.page_size,
            "create_time": [create_start, create_end],
            "uid": uid,
            "channel": [],
            "pay_channel_name": "",
            "pay_channel": "",
            "order_num": "",
            "out_trade_no": "",
            "is_first": "",
            "update_time": [],
            "status": status,
            "not_to_back_cash": "",
        }

    async def _fetch_withdraw_page(
        self,
        *,
        page: int,
        create_start: str,
        create_end: str,
        uid: str = "",
        status: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        payload = await self._post_json(
            WITHDRAW_ORDER_INDEX_PATH,
            body=self._withdraw_body(
                page=page,
                create_start=create_start,
                create_end=create_end,
                uid=uid,
                status=status,
            ),
        )
        data = _response_data(payload)
        if not isinstance(data, dict):
            raise RemoteResponseError("远端提现订单 data 结构无效。")
        items = data.get("items")
        page_info = data.get("pageInfo")
        if not isinstance(items, list) or not isinstance(page_info, dict):
            raise RemoteResponseError("远端提现订单分页结构无效。")
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise RemoteResponseError("远端提现订单包含无效条目。")
            normalized.append(normalize_withdraw_order(item))
        try:
            normalized_page_info = {
                "total": int(page_info.get("total") or 0),
                "current_page": int(page_info.get("currentPage") or page),
                "total_page": int(page_info.get("totalPage") or 0),
            }
        except (TypeError, ValueError) as exc:
            raise RemoteResponseError("远端提现订单分页数字无效。") from exc
        if normalized_page_info["current_page"] != page:
            raise RemoteResponseError("远端提现订单返回页码与请求不一致。")
        return normalized, normalized_page_info

    async def fetch_all_withdraw_orders(
        self,
        *,
        create_start: str,
        create_end: str,
        uid: str = "",
        status: str = "",
    ) -> WithdrawFetchResult:
        orders: list[dict[str, Any]] = []
        fetched_pages = 0
        remote_total = 0
        page = 1
        while True:
            items, page_info = await self._fetch_withdraw_page(
                page=page,
                create_start=create_start,
                create_end=create_end,
                uid=uid,
                status=status,
            )
            fetched_pages += 1
            orders.extend(items)
            remote_total = page_info["total"]
            total_page = page_info["total_page"]
            if total_page > MAX_WITHDRAW_PAGES:
                raise RemoteResponseError("提现订单数量过多，请缩小查询时间范围。")
            if page >= total_page:
                break
            page += 1

        unique_orders: dict[str, dict[str, Any]] = {}
        anonymous_orders: list[dict[str, Any]] = []
        for order in orders:
            order_id = str(order.get("id") or "")
            if order_id:
                unique_orders[order_id] = order
            else:
                anonymous_orders.append(order)
        normalized_orders = [*unique_orders.values(), *anonymous_orders]
        return WithdrawFetchResult(
            orders=normalized_orders,
            fetched_pages=fetched_pages,
            remote_total=remote_total,
            complete=len(normalized_orders) == remote_total,
        )
