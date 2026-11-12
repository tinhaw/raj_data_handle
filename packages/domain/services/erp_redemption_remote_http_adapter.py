"""Concrete Raj admin-backend adapter for authorised redemption executions.

The class is deliberately not registered as an application dependency and no
HTTP route constructs it.  It can only be used by an execution runner that has
already obtained an :class:`ErpRemoteExecutionGrant`; this keeps migrated API
semantics available without enabling remote writes during code deployment.
"""

from __future__ import annotations

import hashlib
import json as json_module
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from openpyxl import load_workbook

from packages.common.totp import generate_totp
from packages.domain.schemas.remote_account import (
    ErpCompatibilityRemoteRecoveryCheckRequest,
    ErpCompatibilityRemoteRecoveryCheckResponse,
    ErpCompatibilityRemoteReuseCheckRequest,
    ErpCompatibilityRemoteReuseCheckResponse,
    ErpCompatibilityRemoteRewardUpdateRequest,
    ErpCompatibilityRemoteVerifyRequest,
    ErpCompatibilityRemoteVerifyResponse,
    ErpRemoteConfigurationVerification,
)
from packages.domain.services.erp_redemption_remote_adapter import (
    ErpRedemptionRemoteAdapter,
    RemoteCancelPublishCommand,
    RemoteCancelPublishResult,
    RemoteCreateCommand,
    RemoteCreateResult,
    RemoteDownloadCommand,
    RemoteDownloadResult,
    RemotePublishCommand,
    RemotePublishResult,
)
from packages.domain.services.erp_redemption_remote_gate import ErpRemoteExecutionGrant
from packages.domain.services.remote_account_session_service import (
    RemoteAccountSession,
    RemoteSessionError,
    response_requires_relogin,
)

LOGIN_PATH = "/api/system/login"
CREATE_PATH = "/api/common/giftCodeConfig/save"
INDEX_PATH = "/api/common/giftCodeConfig/index"
EXPORT_PATH = "/api/common/giftCodeConfig/export"
PUBLISH_PATH = "/api/common/publishTask/save"
CANCEL_PATH = "/api/common/publishTask/cancelAuto"
TAGS_PATH = "/api/common/profileTag/remote"
MAX_EXPORT_BYTES = 16 * 1024 * 1024


class ErpRedemptionRemoteHttpError(ValueError):
    def __init__(
        self, message: str, *, fallback_allowed: bool = False, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.fallback_allowed = fallback_allowed
        self.retryable = retryable


class ErpRedemptionRemoteReviewPending(ErpRedemptionRemoteHttpError):
    """The create request was accepted for review, but no configuration exists yet."""

    def __init__(self) -> None:
        # Retain the established uncertainty prefix for older Java retry guards.
        super().__init__(
            "远端创建结果未确认：待远端主管审核。配置触发风控规则，"
            "需主管审核通过后才可以生成配置；请勿重复创建，审核通过后核对配置再登记和发布。"
        )


@dataclass(frozen=True, slots=True)
class ErpRemoteAccountReadGrant:
    account_id: str
    source_id: str
    operation: Literal["CHECK", "TAGS", "CLAIMS"]
    capability: Literal[
        "ERP_REMOTE_CHECK", "ERP_TAG_READ", "ERP_TAG_SYNC", "ERP_REDEMPTION_CLAIM_READ"
    ]


@dataclass(frozen=True, slots=True)
class RemoteDirectoryTag:
    id: int
    name: str


def _clean(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _nested(payload: object, path: str) -> object | None:
    current = payload
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(payload: object, *paths: str) -> str | None:
    for path in paths:
        value = _clean(_nested(payload, path))
        if value:
            return value
    return None


def _created_configuration_id(payload: object) -> str:
    raw = _nested(payload, "data.id")
    if raw is None:
        raw = _nested(payload, "id")
    value = str(raw).strip() if isinstance(raw, (str, int)) and not isinstance(raw, bool) else ""
    message = _first_text(payload, "message") or ""
    if value == "-1" and "触发风控规则" in message and "需主管审核通过后才可以生成配置" in message:
        raise ErpRedemptionRemoteReviewPending()
    numeric = re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value)
    valid_numeric = re.fullmatch(r"[0-9]+", value) and any(char != "0" for char in value)
    if (
        not value
        or len(value) > 255
        or value.lower() in {"null", "none", "true", "false", "nan", "infinity", "-infinity"}
        or any(ord(char) < 32 for char in value)
        or (numeric and not valid_numeric)
    ):
        # A malformed response does not prove whether the remote write happened.
        # Keep this prefix stable: the Java retry gate preserves this uncertainty.
        raise ErpRedemptionRemoteHttpError(
            "远端创建结果未确认：接口返回无效配置 ID，请先核对远端后台，禁止直接重试。"
        )
    return value


def _extract_token(payload: object) -> str | None:
    if isinstance(payload, dict):
        for key in ("token", "jwt", "access_token", "accessToken"):
            if token := _clean(payload.get(key)):
                return token
        for value in payload.values():
            if token := _extract_token(value):
                return token
    elif isinstance(payload, list):
        for value in payload:
            if token := _extract_token(value):
                return token
    return None


def _success_payload(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ErpRedemptionRemoteHttpError("远端管理后台返回了无法识别的数据。") from exc
    if isinstance(payload, dict):
        code = payload.get("code")
        if payload.get("success") is False or (code is not None and str(code) not in {"0", "200"}):
            raise ErpRedemptionRemoteHttpError(
                _clean(payload.get("message")) or "远端管理后台请求失败。",
                fallback_allowed=str(code).upper()
                in {
                    "401",
                    "403",
                    "419",
                    "440",
                    "429",
                    "500",
                    "502",
                    "503",
                    "504",
                    "TOKEN_EXPIRED",
                    "FORBIDDEN",
                    "UNAUTHORIZED",
                }
                or (payload.get("success") is False and str(code) in {"None", "0", "200"}),
                retryable=str(code) in {"429", "500", "502", "503", "504"},
            )
    return payload


def _native_reward(value):
    try:
        amount = Decimal(str(value))
        return amount / 1000 if amount.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _extract_code_text(content: bytes, expected_count: int = 1) -> str:
    if not content.startswith(b"PK") or len(content) > MAX_EXPORT_BYTES:
        raise ErpRedemptionRemoteHttpError("远端兑换码文件为空、格式无效或超过限制。")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            raise ErpRedemptionRemoteHttpError("远端兑换码文件缺少表头。")
        headers = [_clean(value) or "" for value in header]
        if "兑换码号码" not in headers:
            raise ErpRedemptionRemoteHttpError("远端兑换码文件缺少兑换码号码列。")
        index = headers.index("兑换码号码")
        codes = [
            code for row in rows if index < len(row) and (code := _clean(row[index])) is not None
        ]
    except ErpRedemptionRemoteHttpError:
        raise
    except Exception as exc:
        raise ErpRedemptionRemoteHttpError("远端兑换码文件不是有效 Excel。") from exc
    finally:
        if "workbook" in locals():
            workbook.close()
    if len(codes) != expected_count:
        raise ErpRedemptionRemoteHttpError(
            f"远端兑换码文件应包含 {expected_count} 个兑换码，实际 {len(codes)} 个。"
        )
    if len(set(codes)) != len(codes) or any(
        len(code) > 255 or "\n" in code or "\r" in code for code in codes
    ):
        raise ErpRedemptionRemoteHttpError("远端兑换码文件包含重复或无效号码。")
    return "\n".join(codes)


class RajAdminGiftCodeAdapter(ErpRedemptionRemoteAdapter):
    """Exact HTTP mapping for the current cloud ERP remote operations."""

    def __init__(
        self,
        *,
        account_id: str,
        source_id: str,
        base_url: str,
        username: str,
        password: str,
        totp_secret: str,
        business_timezone: str,
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
        remote_session: RemoteAccountSession | None = None,
    ) -> None:
        self.account_id = account_id
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.business_timezone = ZoneInfo(business_timezone)
        self._token: str | None = None
        self._remote_session = remote_session
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=min(10, timeout_seconds)),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> RajAdminGiftCodeAdapter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _assert_grant(self, grant: ErpRemoteExecutionGrant, operation: str) -> None:
        if (
            grant.account_id != self.account_id
            or grant.source_id != self.source_id
            or grant.operation != operation
            or operation in {"UPDATE", "DELETE"}
            and grant.capability
            != {"UPDATE": "ERP_REDEMPTION_UPDATE", "DELETE": "ERP_REDEMPTION_DELETE"}[operation]
        ):
            raise ErpRedemptionRemoteHttpError("远端执行授权与账号或操作不匹配。")

    def _assert_read_grant(
        self, grant: ErpRemoteAccountReadGrant, operation: Literal["CHECK", "TAGS", "CLAIMS"]
    ) -> None:
        capability_valid = (
            (operation == "CHECK" and grant.capability == "ERP_REMOTE_CHECK")
            or (operation == "TAGS" and grant.capability in {"ERP_TAG_READ", "ERP_TAG_SYNC"})
            or (operation == "CLAIMS" and grant.capability == "ERP_REDEMPTION_CLAIM_READ")
        )
        if (
            grant.account_id != self.account_id
            or grant.source_id != self.source_id
            or grant.operation != operation
            or not capability_valid
        ):
            raise ErpRedemptionRemoteHttpError("远端读取授权与账号或操作不匹配。")

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh_CN",
            "content-type": "application/json;charset=UTF-8",
            "origin": self.base_url,
            "referer": f"{self.base_url}/",
            "user-agent": "RajDataHandle/0.1",
        }
        headers["authorization"] = f"Bearer {token}" if token else "Bearer null"
        return headers

    async def _login(self, *, force: bool = False) -> str:
        if self._remote_session is not None:
            try:
                self._token = await self._remote_session.token(
                    self._login_uncached,
                    force=force,
                    rejected_token=self._token if force else None,
                )
                return self._token
            except RemoteSessionError as exc:
                raise ErpRedemptionRemoteHttpError(
                    str(exc), fallback_allowed=exc.fallback_allowed
                ) from exc
        if self._token and not force:
            return self._token
        self._token = await self._login_uncached()
        return self._token

    async def _login_uncached(self) -> str:
        try:
            response = await self._client.post(
                f"{self.base_url}{LOGIN_PATH}",
                headers=self._headers(),
                json={
                    "username": self.username,
                    "password": self.password,
                    "code": generate_totp(self.totp_secret),
                },
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise ErpRedemptionRemoteHttpError("远端登录失败。", fallback_allowed=True) from exc
        if response.status_code == 429:
            raise ErpRedemptionRemoteHttpError("远端登录次数受限（429）。", fallback_allowed=True)
        if response.status_code >= 400:
            raise ErpRedemptionRemoteHttpError(
                "远端登录返回非成功 HTTP 状态。", fallback_allowed=True
            )
        try:
            token = _extract_token(_success_payload(response))
        except ErpRedemptionRemoteHttpError as exc:
            raise ErpRedemptionRemoteHttpError("远端登录失败。", fallback_allowed=True) from exc
        if not token:
            raise ErpRedemptionRemoteHttpError(
                "远端登录响应中没有访问令牌。", fallback_allowed=True
            )
        return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        bytes_response: bool = False,
        allow_relogin: bool = True,
    ) -> tuple[object | bytes, str | None]:
        token = await self._login()
        try:
            response = await self._client.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(token),
                json=json,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ErpRedemptionRemoteHttpError(
                "无法连接远端管理后台。", fallback_allowed=True, retryable=True
            ) from exc
        if response_requires_relogin(response) and allow_relogin:
            await self._login(force=True)
            return await self._request(
                method,
                path,
                json=json,
                params=params,
                bytes_response=bytes_response,
                allow_relogin=False,
            )
        if response_requires_relogin(response):
            if self._remote_session:
                await self._remote_session.reject(token)
            raise ErpRedemptionRemoteHttpError(
                "重新登录后远端仍拒绝会话，已停止重试。", fallback_allowed=True
            )
        if response.status_code >= 400:
            raise ErpRedemptionRemoteHttpError(
                f"远端管理后台返回 HTTP {response.status_code}。",
                fallback_allowed=response.status_code in {401, 403, 419, 440, 429}
                or response.status_code >= 500,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        request_id = _clean(response.headers.get("x-request-id"))
        return (response.content if bytes_response else _success_payload(response), request_id)

    async def _find_group_key(self, configuration_id: str) -> str | None:
        payload, _ = await self._request(
            "GET",
            INDEX_PATH,
            params={
                "page": 1,
                "pageSize": 100,
                "group_key": "",
                "group_desc": "",
                "valid_type": "",
            },
        )
        items = _nested(payload, "data.items")
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and _first_text(item, "id") == configuration_id:
                return _first_text(item, "group_key", "groupKey")
        return None

    async def check_connection(self, *, grant: ErpRemoteAccountReadGrant) -> tuple[str, str | None]:
        self._assert_read_grant(grant, "CHECK")
        _, request_id = await self._request(
            "GET",
            INDEX_PATH,
            params={
                "page": 1,
                "pageSize": 1,
                "group_key": "",
                "group_desc": "",
                "valid_type": "",
            },
        )
        return "连接正常，已验证远端兑换码配置访问权限。", request_id

    async def fetch_tags(
        self, *, grant: ErpRemoteAccountReadGrant
    ) -> tuple[list[RemoteDirectoryTag], str | None]:
        self._assert_read_grant(grant, "TAGS")
        payload, request_id = await self._request(
            "POST",
            TAGS_PATH,
            json={
                "openPage": False,
                "remoteOption": {
                    "select": ["tag_id", "name"],
                    "filter": {"tag_type": ["!=", 1], "status": 1},
                },
                "page": 1,
                "pageSize": 500,
            },
        )
        data = _nested(payload, "data")
        if not isinstance(data, list):
            raise ErpRedemptionRemoteHttpError("远端标签接口返回格式无效。")
        tags: list[RemoteDirectoryTag] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                tag_id = int(item.get("tag_id") or 0)
            except (TypeError, ValueError):
                continue
            name = _clean(item.get("name"))
            if tag_id > 0 and name:
                tags.append(RemoteDirectoryTag(id=tag_id, name=name))
        return tags, request_id

    async def confirm_special_code_absent(
        self, *, grant: ErpRemoteAccountReadGrant, gift_code: str
    ) -> tuple[int, int]:
        """Require two identical complete directories; the remote gift_code filter is ignored."""
        self._assert_read_grant(grant, "CHECK")
        previous = None
        wanted = gift_code.casefold()
        for _ in range(2):
            records = {}
            pagination = None
            for page in range(1, 201):
                response, _ = await self._request(
                    "GET", INDEX_PATH, params={"page": page, "pageSize": 100}
                )
                data = _nested(response, "data")
                if not isinstance(data, dict):
                    raise ErpRedemptionRemoteHttpError("远端目录格式无效，不能确认兑换码不存在。")
                items, info = data.get("items"), data.get("pageInfo")
                if not isinstance(items, list) or not isinstance(info, dict):
                    raise ErpRedemptionRemoteHttpError("远端目录缺少分页，不能确认兑换码不存在。")
                # Booleans, strings, fractional counts and missing metadata are not evidence.
                fields = [info.get(k) for k in ("currentPage", "total", "totalPage")]
                if any(type(value) is not int for value in fields):
                    raise ErpRedemptionRemoteHttpError("远端目录分页无效，不能确认兑换码不存在。")
                current, total, pages = fields
                if current != page or total < 0 or not 1 <= pages <= 200:
                    raise ErpRedemptionRemoteHttpError("远端目录分页超出核验范围。")
                if pagination is None:
                    pagination = (total, pages)
                if pagination != (total, pages) or (page < pages and not items):
                    raise ErpRedemptionRemoteHttpError("远端目录核验期间发生变化或分页不完整。")
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not str(item.get("id", "")).isdigit()
                        or int(item["id"]) <= 0
                    ):
                        raise ErpRedemptionRemoteHttpError("远端目录配置 ID 无效。")
                    identifier = str(item["id"])
                    if identifier in records or "gift_code" not in item:
                        raise ErpRedemptionRemoteHttpError("远端目录记录重复或缺少码串。")
                    code = str(item.get("gift_code") or "").strip().casefold()
                    if code == wanted:
                        raise ErpRedemptionRemoteHttpError(
                            "远端已存在同码配置，请先核对配置关联，未重新创建。"
                        )
                    records[identifier] = code
                if page == pages:
                    break
            if len(records) != pagination[0]:
                raise ErpRedemptionRemoteHttpError("远端完整目录数量不符，不能确认兑换码不存在。")
            snapshot = (pagination, records)
            if previous is not None and previous != snapshot:
                raise ErpRedemptionRemoteHttpError("两次远端目录不一致，不能确认兑换码不存在。")
            previous = snapshot
        return pagination

    async def check_duplicate_codes(
        self, *, grant: ErpRemoteAccountReadGrant, gift_codes: list[str]
    ) -> dict:
        """Scan twice per market, not per code. Never use the ignored gift_code query filter."""
        self._assert_read_grant(grant, "CHECK")
        wanted = {code.casefold() for code in gift_codes}
        previous = None
        for _ in range(2):
            records = {}
            pagination = None
            for page in range(1, 201):
                response, _ = await self._request(
                    "GET", INDEX_PATH, params={"page": page, "pageSize": 100}
                )
                data = _nested(response, "data")
                if not isinstance(data, dict):
                    raise ErpRedemptionRemoteHttpError("远端查重目录格式无效。")
                items, info = data.get("items"), data.get("pageInfo")
                if not isinstance(items, list) or not isinstance(info, dict):
                    raise ErpRedemptionRemoteHttpError("远端查重目录缺少完整分页。")
                fields = [info.get(k) for k in ("currentPage", "total", "totalPage")]
                if any(type(value) is not int for value in fields):
                    raise ErpRedemptionRemoteHttpError("远端查重目录分页无效。")
                current, total, pages = fields
                if current != page or total < 0 or not 1 <= pages <= 200:
                    raise ErpRedemptionRemoteHttpError("远端查重目录超出核验范围。")
                if pagination is None:
                    pagination = (total, pages)
                if pagination != (total, pages) or (page < pages and not items):
                    raise ErpRedemptionRemoteHttpError(
                        "远端查重期间目录变化或分页不完整，请重新查重。"
                    )
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not str(item.get("id", "")).isdigit()
                        or int(item["id"]) <= 0
                    ):
                        raise ErpRedemptionRemoteHttpError("远端查重目录配置 ID 无效。")
                    identifier = str(item["id"])
                    if identifier in records or "gift_code" not in item:
                        raise ErpRedemptionRemoteHttpError("远端查重目录记录重复或缺少码串。")
                    records[identifier] = str(item.get("gift_code") or "").strip().casefold()
                if page == pages:
                    break
            if len(records) != pagination[0]:
                raise ErpRedemptionRemoteHttpError("远端查重目录数量不符，查重未完成。")
            snapshot = (pagination, records)
            if previous is not None and previous != snapshot:
                raise ErpRedemptionRemoteHttpError("两次远端查重目录不一致，请重新查重。")
            previous = snapshot
        return {
            "complete": True,
            "matches": [{"gift_code": code, "configuration_id": identifier}
                        for identifier, code in records.items() if code in wanted],
            "scanned_rows": pagination[0], "scanned_pages": pagination[1],
        }

    async def _confirm_configuration_absent(
        self, *, grant: ErpRemoteAccountReadGrant, gift_code: str | None, configuration_id: str
    ) -> tuple[int, int]:
        """Require two identical complete directories; the remote gift_code filter is ignored."""
        self._assert_read_grant(grant, "CHECK")
        previous = None
        wanted = gift_code.casefold() if gift_code else None
        for _ in range(2):
            records = {}
            pagination = None
            for page in range(1, 201):
                response, _ = await self._request(
                    "GET", INDEX_PATH, params={"page": page, "pageSize": 100}
                )
                data = _nested(response, "data")
                if not isinstance(data, dict):
                    raise ErpRedemptionRemoteHttpError("远端目录格式无效，不能确认兑换码不存在。")
                items, info = data.get("items"), data.get("pageInfo")
                if not isinstance(items, list) or not isinstance(info, dict):
                    raise ErpRedemptionRemoteHttpError("远端目录缺少分页，不能确认兑换码不存在。")
                # Booleans, strings, fractional counts and missing metadata are not evidence.
                fields = [info.get(k) for k in ("currentPage", "total", "totalPage")]
                if any(type(value) is not int for value in fields):
                    raise ErpRedemptionRemoteHttpError("远端目录分页无效，不能确认兑换码不存在。")
                current, total, pages = fields
                if current != page or total < 0 or not 1 <= pages <= 200:
                    raise ErpRedemptionRemoteHttpError("远端目录分页超出核验范围。")
                if pagination is None:
                    pagination = (total, pages)
                if pagination != (total, pages) or (page < pages and not items):
                    raise ErpRedemptionRemoteHttpError("远端目录核验期间发生变化或分页不完整。")
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not str(item.get("id", "")).isdigit()
                        or int(item["id"]) <= 0
                    ):
                        raise ErpRedemptionRemoteHttpError("远端目录配置 ID 无效。")
                    identifier = str(item["id"])
                    if identifier in records or "gift_code" not in item:
                        raise ErpRedemptionRemoteHttpError("远端目录记录重复或缺少码串。")
                    code = str(item.get("gift_code") or "").strip().casefold()
                    if identifier == configuration_id:
                        raise ErpRedemptionRemoteHttpError("原配置仍在远端目录中，不能确认缺失。")
                    if wanted is not None and code == wanted:
                        raise ErpRedemptionRemoteHttpError(
                            "远端已存在同码配置，请先核对配置关联，未重新创建。"
                        )
                    records[identifier] = code
                if page == pages:
                    break
            if len(records) != pagination[0]:
                raise ErpRedemptionRemoteHttpError("远端完整目录数量不符，不能确认兑换码不存在。")
            snapshot = (pagination, records)
            if previous is not None and previous != snapshot:
                raise ErpRedemptionRemoteHttpError("两次远端目录不一致，不能确认兑换码不存在。")
            previous = snapshot
        return pagination

    async def check_configuration_recovery(
        self,
        *,
        grant: ErpRemoteAccountReadGrant,
        payload: ErpCompatibilityRemoteRecoveryCheckRequest,
        inventory_grant: ErpRemoteExecutionGrant | None = None,
    ) -> ErpCompatibilityRemoteRecoveryCheckResponse:
        """Only a successful empty read plus two complete directories can prove absence."""
        self._assert_read_grant(grant, "CHECK")
        response, _ = await self._request(
            "GET", f"/api/common/giftCodeConfig/read/{payload.remote_configuration_id}"
        )
        data = _nested(response, "data")
        if isinstance(data, dict) and str(data.get("id")) == payload.remote_configuration_id:
            return ErpCompatibilityRemoteRecoveryCheckResponse(
                remote_configuration_id=payload.remote_configuration_id,
                state="PRESENT",
                checked_at=datetime.now(UTC),
            )
        if data != []:
            raise ErpRedemptionRemoteHttpError("远端读取身份或结构不符，不能确认配置缺失。")
        rows, pages = await self._confirm_configuration_absent(
            grant=grant,
            gift_code=payload.gift_code,
            configuration_id=payload.remote_configuration_id,
        )
        if payload.check_inventory:
            if inventory_grant is None or not payload.remote_group_key:
                raise ErpRedemptionRemoteHttpError("缺少库存核验能力或原兑换组标识，不能重建。")
            self._assert_grant(inventory_grant, "DOWNLOAD")
            content, _ = await self._request(
                "POST",
                EXPORT_PATH,
                params={"groupKey": payload.remote_group_key},
                json={},
                bytes_response=True,
            )
            # Zero must be proven by a valid workbook with the native code header.
            _extract_code_text(content, expected_count=0)
        return ErpCompatibilityRemoteRecoveryCheckResponse(
            remote_configuration_id=payload.remote_configuration_id,
            state="ABSENT",
            scanned_rows=rows,
            scanned_pages=pages,
            checked_at=datetime.now(UTC),
        )

    async def check_reusable_configuration(
        self, *, grant: ErpRemoteAccountReadGrant, payload: ErpCompatibilityRemoteReuseCheckRequest
    ) -> ErpCompatibilityRemoteReuseCheckResponse:
        self._assert_read_grant(grant, "CHECK")
        response, _ = await self._request(
            "GET", f"/api/common/giftCodeConfig/read/{payload.remote_configuration_id}"
        )
        data = _nested(response, "data")
        if not isinstance(data, dict) or str(data.get("id")) != payload.remote_configuration_id:
            raise ErpRedemptionRemoteHttpError("远端配置读取未返回指定 ID，不能复用。")
        return self._configuration_expectation(data, payload)

    def _configuration_expectation(
        self, data: dict, payload: ErpCompatibilityRemoteReuseCheckRequest
    ):
        options = payload.options
        expected = {
            "key_number": options.key_number,
            "flow_times": options.flow_times,
            "single_user_limit": options.single_user_limit,
            "single_key_limit": options.single_key_limit,
            "is_need_bind_bank_card": int(options.require_bind_bank_card),
            "is_need_bind_phone": int(options.require_bind_phone),
            "is_need_check_uuid": int(options.check_uuid),
            "uuid_reward_limit": options.uuid_reward_limit,
            "is_need_check_login_ip": int(options.check_login_ip),
            "login_ip_reward_limit": options.login_ip_reward_limit,
            "is_need_check_register_ip": int(options.check_register_ip),
            "register_ip_reward_limit": options.register_ip_reward_limit,
            "gift_type": 1 if payload.gift_code is not None else 0,
            "user_type": 0 if not payload.label_ids else 1,
            "reward_condition_type": 0,
            "refresh_flag": 0,
            "channel_type": 1,
            "agent_uid": 0,
            "clear_status": 0,
            "activity_id": options.activity_id or 0,
            "activity_recharge_count": options.activity_recharge_count or 0,
        }
        differences = []
        for field, value in expected.items():
            try:
                equal = Decimal(str(data.get(field))) == Decimal(value)
            except (InvalidOperation, ValueError):
                equal = False
            if not equal:
                differences.append(field)
        # /read returns raw thousandths, unlike /index and the create form.
        for field, amount in (
            ("reward_min", payload.bonus_amount),
            ("reward_max", payload.bonus_max_amount),
        ):
            try:
                equal = Decimal(str(data.get(field))) == amount * 1000
            except InvalidOperation:
                equal = False
            if not equal:
                differences.append(field)
        # The nonzero activity amount unit has no verified read contract. Do not guess.
        if options.activity_recharge or str(data.get("activity_recharge")) not in {"0", "0.0"}:
            differences.append("activity_recharge")
        if (
            payload.gift_code is not None
            and str(data.get("gift_code", "")).casefold() != payload.gift_code.casefold()
        ):
            differences.append("gift_code")
        try:
            actual_labels = sorted(int(label) for label in data["label_array"])
        except (KeyError, TypeError, ValueError):
            actual_labels = None
        if actual_labels != sorted(payload.label_ids):
            differences.append("label_array")
        for field in (
            "user_array",
            "no_label_array",
            "channel_list",
            "face_channel",
            "no_face_channel",
            "agent_reward_array",
            "company_array",
        ):
            if data.get(field) not in (None, []):
                differences.append(field)
        start = f"{payload.valid_from or payload.claim_date:%Y-%m-%d} 00:00:00"
        end = f"{payload.valid_to or payload.claim_date:%Y-%m-%d} 23:59:59"
        if data.get("start_timestamp") != start or data.get("end_timestamp") != end:
            differences.append("valid_time")
        if str(data.get("status")) not in {"1", "2"}:
            differences.append("status")
        return ErpCompatibilityRemoteReuseCheckResponse(
            remote_configuration_id=payload.remote_configuration_id,
            remote_group_key=_first_text(data, "group_key", "groupKey"),
            actual_bonus_amount=_native_reward(data.get("reward_min")),
            actual_bonus_max_amount=_native_reward(data.get("reward_max")),
            matched=not differences,
            differences=differences,
            checked_at=datetime.now(UTC),
        )

    async def inspect_deletion(self, *, grant, configuration_id: str) -> dict:
        self._assert_read_grant(grant, "CHECK")
        if not re.fullmatch(r"[1-9][0-9]{0,18}", configuration_id):
            raise ErpRedemptionRemoteHttpError("删除配置 ID 无效。")
        response, _ = await self._request(
            "GET", f"/api/common/giftCodeConfig/read/{configuration_id}"
        )
        data = _nested(response, "data")
        if data == []:
            await self._confirm_configuration_absent(
                grant=grant, gift_code=None, configuration_id=configuration_id
            )
            return {"configurationId": configuration_id, "state": "ABSENT"}
        if not isinstance(data, dict) or str(data.get("id")) != configuration_id:
            raise ErpRedemptionRemoteHttpError("远端身份不可核验，未执行删除。")
        # Secret-free confirmation facts; do not retain user arrays or remote response bodies.
        fields = (
            "id",
            "group_key",
            "gift_code",
            "group_desc",
            "remark",
            "gift_type",
            "status",
            "reward_min",
            "reward_max",
            "start_timestamp",
            "end_timestamp",
            "updated_at",
        )
        facts = {key: data.get(key) for key in fields}
        if not facts["group_key"]:
            raise ErpRedemptionRemoteHttpError("配置缺少兑换码组身份，不能删除。")
        fingerprint = hashlib.sha256(
            json_module.dumps(
                facts, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return {
            "configurationId": configuration_id,
            "state": "PRESENT",
            "fingerprint": fingerprint,
            "groupKey": str(facts["group_key"]),
            "giftCode": str(facts["gift_code"] or ""),
            "description": str(facts["group_desc"] or ""),
            "status": str(facts["status"]),
        }

    async def delete_configuration(self, *, grant, read_grant, payload) -> dict:
        self._assert_grant(grant, "DELETE")
        if not payload.execution_confirmed or not payload.expected_fingerprint:
            raise ErpRedemptionRemoteHttpError("请先核对配置并明确确认永久删除。")
        before = await self.inspect_deletion(
            grant=read_grant, configuration_id=payload.remote_configuration_id
        )
        if before["state"] != "PRESENT" or before["fingerprint"] != payload.expected_fingerprint:
            raise ErpRedemptionRemoteHttpError("远端配置已变化，请重新核验确认；未提交删除。")
        # No relogin/replay on destructive writes. Unknown outcomes are reconciled read-only.
        await self._request(
            "DELETE",
            "/api/common/giftCodeConfig/realDelete",
            json={"ids": [int(payload.remote_configuration_id)]},
            allow_relogin=False,
        )
        after = await self.inspect_deletion(
            grant=read_grant, configuration_id=payload.remote_configuration_id
        )
        if after["state"] != "ABSENT":
            raise ErpRedemptionRemoteHttpError("删除后仍能读到配置，结果待核对；禁止重复提交。")
        return after

    async def update_reward_policy(
        self,
        *,
        grant: ErpRemoteExecutionGrant,
        read_grant: ErpRemoteAccountReadGrant,
        payload: ErpCompatibilityRemoteRewardUpdateRequest,
    ) -> ErpCompatibilityRemoteReuseCheckResponse:
        """Update an identified existing configuration's rewards, never delete/recreate it."""
        self._assert_grant(grant, "UPDATE")
        self._assert_read_grant(read_grant, "CHECK")
        if not payload.execution_confirmed:
            raise ErpRedemptionRemoteHttpError("缺少本次奖励修改确认。")
        response, _ = await self._request(
            "GET", f"/api/common/giftCodeConfig/read/{payload.remote_configuration_id}"
        )
        data = _nested(response, "data")
        if not isinstance(data, dict) or str(data.get("id")) != payload.remote_configuration_id:
            raise ErpRedemptionRemoteHttpError("原配置不可读，停止奖励修改；不会新建配置。")
        checked = self._configuration_expectation(data, payload)
        if checked.actual_bonus_amount is None or checked.actual_bonus_max_amount is None:
            raise ErpRedemptionRemoteHttpError("未读到有效的原奖励，停止修改。")
        if set(checked.differences) - {"reward_min", "reward_max"}:
            raise ErpRedemptionRemoteHttpError(
                "远端还有奖励之外的参数不匹配，停止修改并保留原配置。"
            )
        if checked.matched:
            return checked
        if any(
            value != value.to_integral_value()
            for value in (payload.bonus_amount, payload.bonus_max_amount)
        ):
            raise ErpRedemptionRemoteHttpError("远端奖励仅支持整数。")
        # Native edit form fields. Preserve the live description, code, status, audience and limits.
        keys = {
            "id",
            "gift_type",
            "group_key",
            "code_key",
            "valid_type",
            "gift_code",
            "key_number",
            "group_desc",
            "remark",
            "status",
            "flow_times",
            "reward_condition_type",
            "refresh_flag",
            "user_type",
            "label_array",
            "no_label_array",
            "user_array",
            "channel_type",
            "channel_list",
            "face_channel",
            "no_face_channel",
            "agent_uid",
            "agent_reward_array",
            "company_array",
            "clear_status",
            "single_user_limit",
            "single_key_limit",
            "is_need_bind_bank_card",
            "is_need_bind_phone",
            "is_need_check_uuid",
            "uuid_reward_limit",
            "is_need_check_login_ip",
            "login_ip_reward_limit",
            "is_need_check_register_ip",
            "register_ip_reward_limit",
            "activity_recharge",
            "activity_recharge_count",
            "activity_id",
        }
        form = {key: data[key] for key in keys if key in data}
        if not form.get("group_desc") or "remark" not in form:
            raise ErpRedemptionRemoteHttpError("未读到原配置描述及备注，停止修改。")
        for key in (
            "label_array",
            "no_label_array",
            "user_array",
            "channel_list",
            "face_channel",
            "no_face_channel",
            "agent_reward_array",
            "company_array",
        ):
            if key in form and form[key] is None:
                form[key] = []
        form.update(
            reward_min=int(payload.bonus_amount),
            reward_max=int(payload.bonus_max_amount),
            valid_time=[data["start_timestamp"], data["end_timestamp"]],
        )
        await self._request(
            "PUT", f"/api/common/giftCodeConfig/update/{payload.remote_configuration_id}", json=form
        )
        result = await self.check_reusable_configuration(grant=read_grant, payload=payload)
        if not result.matched:
            raise ErpRedemptionRemoteHttpError("奖励修改回读尚未匹配，结果待核对；不要重复提交。")
        return result

    async def create_configuration(
        self, *, grant: ErpRemoteExecutionGrant, command: RemoteCreateCommand
    ) -> RemoteCreateResult:
        self._assert_grant(grant, "CREATE")
        options = command.options
        special_code = command.gift_code
        if special_code is not None and (
            options.key_number != 1 or re.fullmatch(r"[A-Za-z0-9]+", special_code) is None
        ):
            raise ErpRedemptionRemoteHttpError("特殊兑换码每组仅支持一个英文字母或数字码串。")
        all_users = not command.label_ids
        valid_from = command.valid_from or command.claim_date
        valid_to = command.valid_to or command.claim_date
        # The remote bonus-rule mapper requires PHP integers, including for
        # amounts persisted locally as Decimal("5.00"). Never round a reward.
        if any(
            not amount.is_finite() or amount != amount.to_integral_value()
            for amount in (command.bonus_amount, command.bonus_max_amount)
        ):
            raise ErpRedemptionRemoteHttpError("远端兑换金额仅支持整数，请调整兑换金额上下限。")
        payload: dict[str, Any] = {
            # Remote gift-code kind is separate from our deposit/agent campaign type.
            "gift_type": 1 if special_code is not None else 0,
            # Match the console default: audience tags apply without extra claim conditions.
            "reward_condition_type": 0,
            "refresh_flag": 0,
            "flow_times": options.flow_times,
            "status": "2",
            "is_need_check_uuid": int(options.check_uuid),
            "is_need_check_login_ip": int(options.check_login_ip),
            "is_need_check_register_ip": int(options.check_register_ip),
            "user_type": "0" if all_users else "1",
            "label_array": list(command.label_ids),
            "no_label_array": [],
            "channel_type": 1,
            "face_channel": [],
            "no_face_channel": [],
            "is_need_bind_bank_card": int(options.require_bind_bank_card),
            "is_need_bind_phone": int(options.require_bind_phone),
            "remark": command.description,
            "group_desc": command.description,
            "reward_min": int(command.bonus_amount),
            "reward_max": int(command.bonus_max_amount),
            "single_user_limit": options.single_user_limit,
            "single_key_limit": options.single_key_limit,
            "uuid_reward_limit": options.uuid_reward_limit,
            "login_ip_reward_limit": options.login_ip_reward_limit,
            "register_ip_reward_limit": options.register_ip_reward_limit,
            "valid_time": [
                f"{valid_from:%Y-%m-%d} 00:00:00",
                f"{valid_to:%Y-%m-%d} 23:59:59",
            ],
        }
        if special_code is not None:
            payload["gift_code"] = special_code
        else:
            payload["key_number"] = str(options.key_number)
        for key, value in {
            "activity_recharge": options.activity_recharge,
            "activity_recharge_count": options.activity_recharge_count,
            "activity_id": options.activity_id,
        }.items():
            if value is not None:
                payload[key] = str(value) if key == "activity_recharge" else value
        response, request_id = await self._request("POST", CREATE_PATH, json=payload)
        configuration_id = _created_configuration_id(response)
        group_key = _first_text(response, "data.group_key", "data.groupKey")
        if not group_key:
            try:
                group_key = await self._find_group_key(configuration_id)
            except ErpRedemptionRemoteHttpError:
                # Keep the successful save receipt. Download can retry the lookup.
                group_key = None
        return RemoteCreateResult(
            remote_configuration_id=configuration_id,
            remote_group_key=group_key,
            remote_request_id=request_id,
        )

    async def publish(
        self, *, grant: ErpRemoteExecutionGrant, command: RemotePublishCommand
    ) -> RemotePublishResult:
        self._assert_grant(grant, "PUBLISH")
        scheduled = command.mode == "SCHEDULED"
        payload: dict[str, Any] = {
            "env": command.publish_environment,
            "publish_type": "2" if scheduled else "1",
            "cfg_type": 19,
        }
        if scheduled:
            if command.scheduled_publish_at is None:
                raise ErpRedemptionRemoteHttpError("定时发布缺少发布时间。")
            local_time = command.scheduled_publish_at.astimezone(self.business_timezone)
            payload["scheduled_time"] = local_time.strftime("%Y-%m-%d %H:%M:%S")
        response, request_id = await self._request("POST", PUBLISH_PATH, json=payload)
        task_id = _first_text(response, "data.id", "id")
        if not task_id:
            raise ErpRedemptionRemoteHttpError("远端发布接口未返回任务 ID。")
        return RemotePublishResult(
            remote_publish_task_id=task_id,
            scheduled_publish_at=command.scheduled_publish_at,
            remote_request_id=request_id,
        )

    async def download(
        self, *, grant: ErpRemoteExecutionGrant, command: RemoteDownloadCommand
    ) -> RemoteDownloadResult:
        self._assert_grant(grant, "DOWNLOAD")
        group_key = command.remote_group_key or await self._find_group_key(
            command.remote_configuration_id
        )
        if not group_key:
            raise ErpRedemptionRemoteHttpError("远端配置尚未生成兑换码组标识。")
        content, request_id = await self._request(
            "POST", EXPORT_PATH, params={"groupKey": group_key}, json={}, bytes_response=True
        )
        if not isinstance(content, bytes):
            raise ErpRedemptionRemoteHttpError("远端兑换码下载响应无效。")
        return RemoteDownloadResult(
            redemption_code=_extract_code_text(content, command.key_number),
            remote_group_key=group_key,
            remote_request_id=request_id,
        )

    async def _verification_rows(self, path: str, wanted: set[str]):
        """Bound pagination; absence is only proven after the last advertised page."""
        found: dict[str, dict] = {}
        for page in range(1, 51):
            payload, _ = await self._request("GET", path, params={"page": page, "pageSize": 100})
            rows = _nested(payload, "data.items")
            page_info = _nested(payload, "data.pageInfo")
            if not isinstance(rows, list) or not isinstance(page_info, dict):
                raise ErpRedemptionRemoteHttpError("远端核验列表缺少有效分页信息。")
            try:
                total_pages = int(page_info["totalPage"])
                current_page = int(page_info["currentPage"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ErpRedemptionRemoteHttpError("远端核验分页信息无效。") from exc
            if current_page != page or total_pages < 0:
                raise ErpRedemptionRemoteHttpError("远端核验分页不一致。")
            for row in rows:
                if isinstance(row, dict) and (row_id := _first_text(row, "id")) in wanted:
                    if row_id in found and found[row_id] != row:
                        raise ErpRedemptionRemoteHttpError("远端核验发现重复配置标识。")
                    found[row_id] = row
            if wanted <= found.keys() or page >= total_pages:
                return found
        raise ErpRedemptionRemoteHttpError("远端核验未查完所有分页，请缩小范围后重试。")

    async def verify_publication(
        self, *, grant: ErpRemoteExecutionGrant, payload: ErpCompatibilityRemoteVerifyRequest
    ) -> ErpCompatibilityRemoteVerifyResponse:
        self._assert_grant(grant, "DOWNLOAD")
        rows = await self._verification_rows(
            "/api/common/publishTask/index", {payload.remote_publish_task_id}
        )
        task = rows.get(payload.remote_publish_task_id)
        status = None
        state = "UNKNOWN"
        if (
            task
            and str(task.get("cfg_type")) == "19"
            and task.get("env") == payload.publish_environment
        ):
            raw_status = str(task.get("status"))
            if raw_status in {"0", "1", "2", "3", "4", "5"}:
                status = int(raw_status)
                state = {
                    0: "WAITING",
                    1: "RUNNING",
                    2: "FAILED",
                    3: "COMPLETED",
                    4: "COMPLETED",
                    5: "CANCELLED",
                }[status]
        configurations = [
            ErpRemoteConfigurationVerification(
                configuration_id=ref.configuration_id, state="UNKNOWN"
            )
            for ref in payload.configurations
        ]
        configuration_error = None
        if state == "COMPLETED" and payload.configurations:
            try:
                configs = await self._verification_rows(
                    INDEX_PATH, {ref.configuration_id for ref in payload.configurations}
                )
                for ref, verified in zip(payload.configurations, configurations, strict=True):
                    row = configs.get(ref.configuration_id)
                    verified.state = "MISSING"
                    if row is not None:
                        count = (
                            "1"
                            if str(row.get("gift_type")) == "1" and _first_text(row, "gift_code")
                            else str(row.get("key_number"))
                        )
                        verified.state = (
                            "MATCHED"
                            if (
                                bool(ref.group_key)
                                and _first_text(row, "group_key", "groupKey") == ref.group_key
                                and count == str(ref.key_number)
                            )
                            else "MISMATCH"
                        )
            except ErpRedemptionRemoteHttpError as exc:
                # A denied configuration query must not erase a proven task result.
                configuration_error = str(exc)
        return ErpCompatibilityRemoteVerifyResponse(
            remote_publish_task_id=payload.remote_publish_task_id,
            remote_status=status,
            publication_state=state,
            can_cancel=state == "WAITING" and str(task.get("publish_type")) == "2",
            configurations=configurations,
            configuration_error=configuration_error,
            checked_at=datetime.now(UTC),
        )

    async def cancel_publish(
        self, *, grant: ErpRemoteExecutionGrant, command: RemoteCancelPublishCommand
    ) -> RemoteCancelPublishResult:
        self._assert_grant(grant, "CANCEL")
        response, request_id = await self._request(
            "POST",
            CANCEL_PATH,
            json={
                "id": int(command.remote_publish_task_id)
                if command.remote_publish_task_id.isascii()
                and command.remote_publish_task_id.isdecimal()
                else command.remote_publish_task_id
            },
        )
        result = _nested(response, "data.ret")
        if str(result) != "1":
            raise ErpRedemptionRemoteHttpError("远端未确认撤销定时发布。")
        return RemoteCancelPublishResult(remote_request_id=request_id)
