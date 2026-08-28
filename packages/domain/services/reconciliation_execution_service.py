from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import (
    OrderReconciliationResult,
    ReconciliationBatch,
    SourceConfig,
    StoredFileObject,
    StoredFileReference,
)
from packages.domain.services.batch_service import (
    resolve_payment_column_mapping,
    transition_batch,
)
from packages.domain.services.payment_import_service import (
    PaymentImportError,
    PaymentOrderGroup,
    import_payment_orders,
)
from packages.domain.services.reconciliation_engine import (
    ReconciliationDecision,
    compare_with_remote_orders,
)
from packages.domain.services.remote_account_credentials import (
    RemoteAccountCredentialsError,
    decrypt_remote_account_credentials,
    resolve_default_remote_account_credentials,
)
from packages.domain.services.remote_charge_service import (
    RajAdminChargeClient,
    RemoteChargeError,
)
from packages.storage.local import LocalFileStorage


class ReconciliationExecutionError(RuntimeError):
    pass


def _wall_time(value: str, timezone_name: str) -> datetime:
    try:
        timezone = ZoneInfo(timezone_name)
        parsed = datetime.fromisoformat(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ReconciliationExecutionError("批次时间口径无效。") from exc
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)


def _remote_time(value: object, timezone_name: str) -> datetime | None:
    if value is None or str(value).strip() in {"", "0"}:
        return None
    raw = str(value).strip()
    parsed: datetime | None = None
    for parser in (
        datetime.fromisoformat,
        lambda item: datetime.strptime(item, "%Y/%m/%d %H:%M:%S"),
        lambda item: datetime.strptime(item, "%d-%m-%Y %H:%M:%S"),
    ):
        try:
            parsed = parser(raw)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    timezone = ZoneInfo(timezone_name)
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed.astimezone(timezone)


def _template_snapshot(batch: ReconciliationBatch) -> tuple[dict[str, Any], dict[str, Any]]:
    detection = batch.parameters_json.get("templateDetection")
    if not isinstance(detection, dict):
        raise ReconciliationExecutionError("支付模板快照缺失。")
    template = detection.get("template")
    if not isinstance(template, dict):
        raise ReconciliationExecutionError("支付模板快照缺失。")
    return detection, template


async def _uploaded_path(
    session: AsyncSession,
    storage: LocalFileStorage,
    batch_id: str,
) -> Path:
    row = (
        await session.execute(
            select(StoredFileObject)
            .join(StoredFileReference, StoredFileReference.file_object_id == StoredFileObject.id)
            .where(StoredFileReference.batch_id == batch_id)
        )
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise ReconciliationExecutionError("原始支付文件已过期或不存在。")
    path = storage.resolve_path(row.storage_key)
    if not path.is_file():
        raise ReconciliationExecutionError("原始支付文件已过期或不存在。")
    return path


async def _set_progress(
    session: AsyncSession,
    batch: ReconciliationBatch,
    **values: Any,
) -> None:
    batch.progress_json = {**batch.progress_json, **values}
    await session.commit()


async def _cancelled(session: AsyncSession, batch: ReconciliationBatch) -> bool:
    await session.refresh(batch)
    return batch.status in {"cancelling", "cancelled"}


def _result_payload(
    payment: PaymentOrderGroup,
    decision: ReconciliationDecision,
) -> dict[str, Any]:
    return {
        "platformKey": payment.platform_key,
        "amount": str(payment.amount) if payment.amount is not None else None,
        "currency": payment.currency,
        "paymentTime": payment.payment_time.isoformat() if payment.payment_time else None,
        "sourceSheet": payment.source_sheet,
        "sourceRowNumbers": payment.source_row_numbers,
        "duplicateCount": payment.duplicate_count,
        "remoteOrder": decision.remote_order,
    }


async def _save_results(
    session: AsyncSession,
    *,
    batch: ReconciliationBatch,
    decisions: list[tuple[PaymentOrderGroup, ReconciliationDecision]],
) -> None:
    await session.execute(
        delete(OrderReconciliationResult).where(OrderReconciliationResult.batch_id == batch.id)
    )
    for payment, decision in decisions:
        session.add(
            OrderReconciliationResult(
                batch_id=batch.id,
                order_group_id=payment.order_group_id,
                result_status=decision.result_status,
                payment_status_raw=payment.payment_status_raw,
                payment_status_group=payment.payment_status_group,
                merchant_order_no=payment.merchant_order_no,
                platform_order_no=payment.platform_order_no,
                payload_json=_result_payload(payment, decision),
                is_final=False,
            )
        )
    await session.commit()


async def execute_reconciliation_batch(
    session: AsyncSession,
    *,
    batch: ReconciliationBatch,
    storage: LocalFileStorage,
    settings: Settings | None = None,
) -> None:
    current_settings = settings or get_settings()
    await transition_batch(
        session,
        batch=batch,
        to_status="validating",
        actor_user_id=None,
    )
    try:
        source = await session.get(SourceConfig, batch.source_id)
        if (
            source is None
            or not source.enabled
            or not source.base_url
            or source.config_version != batch.source_config_version
        ):
            raise ReconciliationExecutionError("盘口配置已变化或不可用，请创建重新比对版本。")
        credential_envelope = await resolve_default_remote_account_credentials(
            session,
            source=source,
        )
        if credential_envelope is None:
            raise ReconciliationExecutionError("盘口尚未配置可用的默认远端账号。")
        credentials = decrypt_remote_account_credentials(
            credential_envelope,
            settings=current_settings,
        )
        detection, template = _template_snapshot(batch)
        window = batch.parameters_json["comparisonWindow"]
        column_mapping = resolve_payment_column_mapping(batch.parameters_json, template)
        detected_headers = detection.get("detectedHeaders")
        if isinstance(detected_headers, list) and detected_headers:
            column_mapping["candidate_time_fields"] = list(detected_headers)
        path = await _uploaded_path(session, storage, batch.id)
        imported = import_payment_orders(
            path,
            file_suffix=Path(batch.uploaded_file_name).suffix,
            platform_key=str(template["platformKey"]),
            source_sheet=str(detection["sourceSheet"]),
            header_row=int(detection["headerRow"]),
            column_mapping=column_mapping,
            success_status_values=list(template["successStatusValues"]),
            payment_time_field=str(window["paymentTimeField"]),
            payment_timezone=str(window["paymentTimezone"]),
            window_start=str(window["start"]),
            window_end=str(window["end"]),
            currency=str(batch.parameters_json["currency"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        PaymentImportError,
        ReconciliationExecutionError,
        RemoteAccountCredentialsError,
    ) as exc:
        batch.error_category = "validation_error"
        batch.error_message = str(exc)[:500]
        await transition_batch(
            session,
            batch=batch,
            to_status="failed",
            actor_user_id=None,
        )
        return

    await _set_progress(
        session,
        batch,
        stage="fetching_remote",
        sourceRows=imported.source_rows,
        includedRows=imported.included_rows,
        excludedOutsideWindow=imported.excluded_outside_window,
    )
    if await _cancelled(session, batch):
        return
    await transition_batch(
        session,
        batch=batch,
        to_status="fetching_remote",
        actor_user_id=None,
    )
    remote_timezone = str(window["remoteBusinessTimezone"])
    try:
        remote_lower = _wall_time(str(window["start"]), remote_timezone)
        remote_upper = _wall_time(str(window["end"]), remote_timezone)
    except ReconciliationExecutionError as exc:
        batch.error_category = "validation_error"
        batch.error_message = str(exc)
        await transition_batch(
            session,
            batch=batch,
            to_status="failed",
            actor_user_id=None,
        )
        return
    query_lower = remote_lower - timedelta(hours=int(window.get("bufferBeforeHours") or 0))
    query_upper = remote_upper + timedelta(hours=int(window.get("bufferAfterHours") or 0))
    channels = [
        {"code": str(item["code"]), "label": str(item["label"])}
        for item in batch.parameters_json["selectedChannels"]
    ]
    try:
        async with RajAdminChargeClient(
            base_url=source.base_url,
            username=credentials["username"],
            password=credentials["password"],
            totp_secret=credentials["totp_secret"],
        ) as client:
            remote_orders, fetched_pages = await client.fetch_all_charge_orders(
                channels=channels,
                create_start=query_lower.strftime("%Y-%m-%d %H:%M:%S"),
                create_end=query_upper.strftime("%Y-%m-%d %H:%M:%S"),
            )
            remote_time_field = str(window["remoteTimeField"])
            filtered_remote = [
                order
                for order in remote_orders
                if (
                    (parsed := _remote_time(order.get(remote_time_field), remote_timezone))
                    is not None
                    and remote_lower <= parsed <= remote_upper
                )
            ]
            await _set_progress(
                session,
                batch,
                remoteRows=len(filtered_remote),
                remoteFetchedRows=len(remote_orders),
                remotePages=fetched_pages,
            )
            if await _cancelled(session, batch):
                return
            await transition_batch(
                session,
                batch=batch,
                to_status="comparing",
                actor_user_id=None,
            )
            decisions: list[tuple[PaymentOrderGroup, ReconciliationDecision]] = []
            candidates: list[PaymentOrderGroup] = []
            for payment in imported.groups:
                decision = compare_with_remote_orders(payment, filtered_remote)
                if decision is None:
                    candidates.append(payment)
                else:
                    decisions.append((payment, decision))
            await _set_progress(
                session,
                batch,
                stage="comparing",
                processedRows=len(imported.groups) - len(candidates),
                candidateMissing=len(candidates),
            )
            if candidates:
                if await _cancelled(session, batch):
                    return
                await transition_batch(
                    session,
                    batch=batch,
                    to_status="rechecking",
                    actor_user_id=None,
                )
                for index, payment in enumerate(candidates, start=1):
                    if index % 25 == 1 and await _cancelled(session, batch):
                        return
                    exact = await client.exact_search(
                        channels=channels,
                        platform_order_no=payment.platform_order_no,
                        create_start=query_lower.strftime("%Y-%m-%d %H:%M:%S"),
                        create_end=query_upper.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    decision = compare_with_remote_orders(
                        payment,
                        exact.orders,
                        after_recheck=True,
                    )
                    if decision is None:
                        if not exact.complete:
                            status = "recheck_inconclusive"
                        else:
                            status = "confirmed_missing"
                        decision = ReconciliationDecision(status, None)
                    decisions.append((payment, decision))
                    if index % 25 == 0 or index == len(candidates):
                        await _set_progress(
                            session,
                            batch,
                            stage="rechecking",
                            recheckedRows=index,
                            processedRows=len(decisions),
                        )
    except (RemoteChargeError, KeyError, ValueError, ZoneInfoNotFoundError):
        batch.error_category = "remote_read_incomplete"
        batch.error_message = "远端只读拉取或精确复查未完整成功，未发布确认遗漏结论。"
        await transition_batch(
            session,
            batch=batch,
            to_status="comparison_incomplete",
            actor_user_id=None,
        )
        return

    await _save_results(session, batch=batch, decisions=decisions)
    if await _cancelled(session, batch):
        return
    await _set_progress(
        session,
        batch,
        stage="completed",
        processedRows=len(decisions),
    )
    if await _cancelled(session, batch):
        return
    await session.execute(
        update(OrderReconciliationResult)
        .where(OrderReconciliationResult.batch_id == batch.id)
        .values(is_final=True)
    )
    await transition_batch(
        session,
        batch=batch,
        to_status="completed",
        actor_user_id=None,
    )
