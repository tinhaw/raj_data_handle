from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from packages.common.totp import generate_totp

LOGIN_PATH = "/api/system/login"
CHARGE_ORDER_INDEX_PATH = "/api/operate/chargeOrder/index"
CHARGE_CHANNEL_PATH = "/api/operate/chargeOrder/payChannel"
REMOTE_SUCCESS_STATUS = 1
REMOTE_READ_PATHS = {CHARGE_ORDER_INDEX_PATH, CHARGE_CHANNEL_PATH}
AUTH_FAILURE_STATUSES = {401, 403, 419, 440}


class RemoteChargeError(RuntimeError):
    pass


class RemoteAuthenticationError(RemoteChargeError):
    pass


class RemoteResponseError(RemoteChargeError):
    pass


@dataclass(frozen=True, slots=True)
class ExactSearchResult:
    orders: list[dict[str, Any]]
    complete: bool


def _extract_token(payload: object) -> str | None:
    token_keys = {"token", "jwt", "access_token", "accessToken"}
    if isinstance(payload, dict):
        for key in token_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                token = value.strip()
                if token.lower().startswith("bearer "):
                    return token.split(None, 1)[1].strip()
                return token
        for value in payload.values():
            token = _extract_token(value)
            if token:
                return token
    elif isinstance(payload, list):
        for value in payload:
            token = _extract_token(value)
            if token:
                return token
    return None


def _response_data(payload: object) -> Any:
    if not isinstance(payload, dict):
        raise RemoteResponseError("远端响应不是 JSON 对象。")
    if payload.get("success") is False:
        raise RemoteResponseError("远端接口返回失败状态。")
    code = payload.get("code")
    if code not in (None, 0, 200, "200"):
        raise RemoteResponseError("远端接口返回非成功业务码。")
    return payload.get("data")


class RajAdminChargeClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        totp_secret: str,
        timeout_seconds: float = 30.0,
        page_size: int = 100,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.page_size = page_size
        self._token: str | None = None
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> RajAdminChargeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh_CN",
            "content-type": "application/json;charset=UTF-8",
            "referer": f"{self.base_url}/",
            "user-agent": "RajDataHandle/0.1",
        }

    async def login(self, *, force: bool = False) -> str:
        if self._token and not force:
            return self._token
        try:
            code = generate_totp(self.totp_secret)
        except ValueError as exc:
            raise RemoteAuthenticationError(str(exc)) from exc
        try:
            response = await self._client.post(
                f"{self.base_url}{LOGIN_PATH}",
                headers=self._base_headers(),
                json={
                    "username": self.username,
                    "password": self.password,
                    "code": code,
                },
            )
        except httpx.HTTPError as exc:
            raise RemoteAuthenticationError("远端登录请求失败。") from exc
        if response.status_code >= 400:
            raise RemoteAuthenticationError("远端登录返回非成功 HTTP 状态。")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RemoteAuthenticationError("远端登录响应不是有效 JSON。") from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            raise RemoteAuthenticationError("远端登录被拒绝。")
        token = _extract_token(payload)
        if not token:
            raise RemoteAuthenticationError("远端登录响应中没有 JWT。")
        self._token = token
        return token

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_relogin: bool = True,
    ) -> object:
        if path not in REMOTE_READ_PATHS:
            raise RemoteChargeError("请求路径不在充值只读 Allowlist 中。")
        token = await self.login()
        headers = {**self._base_headers(), "authorization": f"Bearer {token}"}
        try:
            response = await self._client.get(
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise RemoteResponseError("远端只读请求失败。") from exc
        if response.status_code in AUTH_FAILURE_STATUSES and allow_relogin:
            await self.login(force=True)
            return await self._get_json(path, params=params, allow_relogin=False)
        if response.status_code >= 400:
            raise RemoteResponseError("远端只读接口返回非成功 HTTP 状态。")
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteResponseError("远端只读接口响应不是有效 JSON。") from exc

    async def fetch_channels(self) -> list[dict[str, str]]:
        data = _response_data(await self._get_json(CHARGE_CHANNEL_PATH))
        if not isinstance(data, list):
            raise RemoteResponseError("远端充值渠道字典结构无效。")
        channels: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                raise RemoteResponseError("远端充值渠道字典包含无效条目。")
            code = str(item.get("value") or "").strip()
            label = str(item.get("label") or "").strip()
            if not code or not label:
                raise RemoteResponseError("远端充值渠道字典缺少代码或名称。")
            channels.append({"code": code, "label": label})
        if not channels:
            raise RemoteResponseError("远端充值渠道名称字典为空。")
        return channels

    def _charge_params(
        self,
        *,
        page: int,
        channel_code: str,
        create_start: str | None = None,
        create_end: str | None = None,
        order_num: str = "",
        out_trade_no: str = "",
    ) -> dict[str, Any]:
        return {
            "page": page,
            "pageSize": self.page_size,
            "create_time[0]": create_start or "",
            "create_time[1]": create_end or "",
            "uid": "",
            "first_pay": "",
            "order_num": order_num,
            "charge_id": "",
            "charge_type": "",
            "pay_channel_type": "",
            "pay_channel_name": "",
            "pay_method": channel_code,
            "pay_type": "",
            "out_trade_no": out_trade_no,
            "status": "",
            "recent": 0,
        }

    async def _fetch_charge_page(
        self,
        *,
        page: int,
        channel_code: str,
        channel_label: str,
        create_start: str | None = None,
        create_end: str | None = None,
        order_num: str = "",
        out_trade_no: str = "",
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        payload = await self._get_json(
            CHARGE_ORDER_INDEX_PATH,
            params=self._charge_params(
                page=page,
                channel_code=channel_code,
                create_start=create_start,
                create_end=create_end,
                order_num=order_num,
                out_trade_no=out_trade_no,
            ),
        )
        data = _response_data(payload)
        if not isinstance(data, dict):
            raise RemoteResponseError("远端充值订单 data 结构无效。")
        items = data.get("items")
        page_info = data.get("pageInfo")
        if not isinstance(items, list) or not isinstance(page_info, dict):
            raise RemoteResponseError("远端充值订单分页结构无效。")
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise RemoteResponseError("远端充值订单包含无效条目。")
            normalized.append(
                {
                    **item,
                    "_remote_channel_code": channel_code,
                    "_remote_channel_label": channel_label,
                }
            )
        try:
            normalized_page_info = {
                "total": int(page_info.get("total") or 0),
                "current_page": int(page_info.get("currentPage") or page),
                "total_page": int(page_info.get("totalPage") or 0),
            }
        except (TypeError, ValueError) as exc:
            raise RemoteResponseError("远端充值订单分页数字无效。") from exc
        if normalized_page_info["current_page"] != page:
            raise RemoteResponseError("远端充值订单返回页码与请求不一致。")
        return normalized, normalized_page_info

    async def fetch_all_charge_orders(
        self,
        *,
        channels: list[dict[str, str]],
        create_start: str,
        create_end: str,
    ) -> tuple[list[dict[str, Any]], int]:
        all_orders: list[dict[str, Any]] = []
        fetched_pages = 0
        for channel in channels:
            page = 1
            channel_orders: list[dict[str, Any]] = []
            expected_total = 0
            while True:
                items, page_info = await self._fetch_charge_page(
                    page=page,
                    channel_code=channel["code"],
                    channel_label=channel["label"],
                    create_start=create_start,
                    create_end=create_end,
                )
                fetched_pages += 1
                channel_orders.extend(items)
                expected_total = page_info["total"]
                total_page = page_info["total_page"]
                if total_page > 100_000:
                    raise RemoteResponseError("远端充值订单分页数量异常。")
                if page >= total_page:
                    break
                page += 1
            if len(channel_orders) != expected_total:
                raise RemoteResponseError("远端充值订单累计数量与 pageInfo.total 不一致。")
            all_orders.extend(channel_orders)
        return all_orders, fetched_pages

    async def exact_search(
        self,
        *,
        channels: list[dict[str, str]],
        platform_order_no: str | None,
    ) -> ExactSearchResult:
        found: dict[str, dict[str, Any]] = {}
        complete = True
        if not platform_order_no:
            return ExactSearchResult(orders=[], complete=complete)
        for channel in channels:
            try:
                items, page_info = await self._fetch_charge_page(
                    page=1,
                    channel_code=channel["code"],
                    channel_label=channel["label"],
                    out_trade_no=platform_order_no,
                )
                if page_info["total_page"] > 1 or len(items) != page_info["total"]:
                    complete = False
                for item in items:
                    identity = str(
                        item.get("id")
                        or item.get("order_num")
                        or item.get("out_trade_no")
                        or ""
                    )
                    if identity:
                        found[identity] = item
            except RemoteChargeError:
                complete = False
        return ExactSearchResult(orders=list(found.values()), complete=complete)
