from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.settings import Settings, get_settings
from packages.domain.models import (
    BatchActivityLog,
    OrderReconciliationResult,
    ReconciliationBatch,
    SourceConfig,
    StoredFileObject,
    StoredFileReference,
    UserNotification,
)
from packages.domain.services.batch_state import (
    CANCELLABLE_BATCH_STATUSES,
    TERMINAL_BATCH_STATUSES,
    ensure_transition,
)
from packages.domain.services.payment_template_service import (
    TemplateDetectionError,
    detect_payment_template,
    detection_snapshot,
)
from packages.domain.services.system_setting_service import get_retention_settings
from packages.storage.base import FileStorage


class BatchValidationError(ValueError):
    pass


def _identity_key(
    *,
    file_sha256: str,
    source_id: str,
    business_type: str,
    parameters: dict[str, Any],
) -> str:
    payload = {
        "file": file_sha256,
        "source": source_id,
        "businessType": business_type,
        "parameters": parameters,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def list_batches(
    session: AsyncSession,
    *,
    source_id: str | None = None,
    business_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ReconciliationBatch], int]:
    filters = []
    if source_id:
        filters.append(ReconciliationBatch.source_id == source_id)
    if business_type:
        filters.append(ReconciliationBatch.business_type == business_type)
    if status:
        filters.append(ReconciliationBatch.status == status)
    statement = (
        select(ReconciliationBatch)
        .where(*filters)
        .order_by(ReconciliationBatch.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_statement = select(func.count()).select_from(ReconciliationBatch).where(*filters)
    rows = list(await session.scalars(statement))
    total = int(await session.scalar(count_statement) or 0)
    return rows, total


async def get_batch(session: AsyncSession, batch_id: str) -> ReconciliationBatch:
    batch = await session.get(ReconciliationBatch, batch_id)
    if batch is None:
        raise BatchValidationError("比对批次不存在。")
    return batch


def _validate_execution_parameters(batch: ReconciliationBatch) -> None:
    if batch.business_type != "payin":
        raise BatchValidationError("当前执行器只支持充值 / 代收比对。")
    parameters = batch.parameters_json
    detection = parameters.get("templateDetection")
    if not isinstance(detection, dict) or detection.get("status") != "matched":
        raise BatchValidationError("支付文件尚未匹配已发布模板，暂不能启动比对。")
    template = detection.get("template")
    if not isinstance(template, dict) or template.get("businessType") != "payin":
        raise BatchValidationError("支付模板不是充值 / 代收模板。")
    channels = parameters.get("selectedChannels")
    if not isinstance(channels, list) or not channels:
        raise BatchValidationError("请至少确认一个远端充值渠道。")
    platform_key = str(template.get("platformKey") or "")
    for channel in channels:
        if (
            not isinstance(channel, dict)
            or not str(channel.get("code") or "").strip()
            or not str(channel.get("label") or "").strip()
            or channel.get("platformKey") != platform_key
        ):
            raise BatchValidationError("所选渠道与支付模板平台不一致。")
    window = parameters.get("comparisonWindow")
    required_window_fields = {
        "start",
        "end",
        "paymentTimeField",
        "paymentTimezone",
        "remoteTimeField",
        "remoteBusinessTimezone",
    }
    if not isinstance(window, dict) or not all(window.get(key) for key in required_window_fields):
        raise BatchValidationError("请完整确认支付与远端时间口径。")
    if window.get("remoteTimeField") not in {"create_time", "pay_time"}:
        raise BatchValidationError("远端时间字段只能是 create_time 或 pay_time。")
    if str(parameters.get("currency") or "").upper() != batch.source_currency:
        raise BatchValidationError("批次币种必须与盘口币种一致。")


async def confirm_batch(
    session: AsyncSession,
    *,
    batch_id: str,
    actor_user_id: int,
) -> ReconciliationBatch:
    batch = await get_batch(session, batch_id)
    if batch.status != "awaiting_confirmation":
        raise BatchValidationError("只有待确认草稿可以启动比对。")
    _validate_execution_parameters(batch)
    batch.execution_requested_by = actor_user_id
    batch.progress_json = {"stage": "queued", "processedRows": 0}
    return await transition_batch(
        session,
        batch=batch,
        to_status="queued",
        actor_user_id=actor_user_id,
        metadata={"parametersConfirmed": True},
    )


async def create_batch_from_upload(
    session: AsyncSession,
    *,
    storage: FileStorage,
    upload: UploadFile,
    source_id: str,
    business_type: str,
    header_row: int | None = None,
    parameters: dict[str, Any],
    actor_user_id: int,
    settings: Settings | None = None,
) -> tuple[ReconciliationBatch, bool]:
    current_settings = settings or get_settings()
    retention = await get_retention_settings(session, defaults=current_settings)
    if business_type not in {"payin", "payout"}:
        raise BatchValidationError("业务类型只能是 payin 或 payout。")
    file_name = (upload.filename or "").strip()
    suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix not in {"xlsx", "csv"}:
        raise BatchValidationError("当前只支持 .xlsx 和 .csv 文件。")
    source = await session.get(SourceConfig, source_id)
    if source is None or not source.enabled:
        raise BatchValidationError("请选择已启用的盘口。")

    try:
        detection = await detect_payment_template(session, upload, header_row=header_row)
    except TemplateDetectionError as exc:
        raise BatchValidationError(str(exc)) from exc
    if detection.template is not None and detection.template.business_type != business_type:
        raise BatchValidationError(
            f"文件识别为 {detection.template.business_type} 模板，不能用于 {business_type} 比对。"
        )
    parameters = {
        **parameters,
        "templateDetection": detection_snapshot(detection),
    }
    stored = await storage.store_upload(upload)
    identity = _identity_key(
        file_sha256=stored.content_sha256,
        source_id=source_id,
        business_type=business_type,
        parameters=parameters,
    )
    existing = await session.scalar(
        select(ReconciliationBatch)
        .where(ReconciliationBatch.comparison_identity_key == identity)
        .order_by(ReconciliationBatch.run_version.desc())
    )
    if existing is not None and existing.status not in {"failed", "cancelled"}:
        return existing, True

    file_object = await session.scalar(
        select(StoredFileObject).where(StoredFileObject.content_sha256 == stored.content_sha256)
    )
    if file_object is None:
        file_object = StoredFileObject(
            content_sha256=stored.content_sha256,
            storage_key=stored.storage_key,
            byte_size=stored.byte_size,
            content_type=stored.content_type,
        )
        session.add(file_object)
        await session.flush()
    elif file_object.deleted_at is not None:
        file_object.storage_key = stored.storage_key
        file_object.byte_size = stored.byte_size
        file_object.content_type = stored.content_type
        file_object.deleted_at = None

    now = datetime.now(UTC)
    batch = ReconciliationBatch(
        comparison_identity_key=identity,
        source_id=source.source_id,
        source_display_name=source.display_name,
        source_config_version=source.config_version,
        source_business_timezone=source.business_timezone,
        source_currency=source.currency,
        business_type=business_type,
        status="awaiting_confirmation",
        uploaded_file_name=file_name,
        uploaded_file_sha256=stored.content_sha256,
        parameters_json=parameters,
        progress_json={"stage": "awaiting_confirmation", "processedRows": 0},
        execution_requested_by=actor_user_id,
        created_by=actor_user_id,
        result_expires_at=now + timedelta(days=retention.result_retention_days),
    )
    session.add(batch)
    await session.flush()
    session.add(
        StoredFileReference(
            file_object_id=file_object.id,
            batch_id=batch.id,
            expires_at=now + timedelta(days=retention.uploaded_file_retention_days),
        )
    )
    session.add(
        BatchActivityLog(
            batch_id=batch.id,
            actor_user_id=actor_user_id,
            action="batch.create",
            to_status=batch.status,
            metadata_json={"fileSha256": stored.content_sha256},
        )
    )
    await session.commit()
    return batch, False


async def transition_batch(
    session: AsyncSession,
    *,
    batch: ReconciliationBatch,
    to_status: str,
    actor_user_id: int | None,
    metadata: dict[str, Any] | None = None,
) -> ReconciliationBatch:
    transition = ensure_transition(batch.status, to_status)
    batch.status = to_status
    now = datetime.now(UTC)
    if to_status == "validating" and batch.started_at is None:
        batch.started_at = now
    if to_status in TERMINAL_BATCH_STATUSES:
        batch.completed_at = now
        batch.is_final = to_status == "completed"
    session.add(
        BatchActivityLog(
            batch_id=batch.id,
            actor_user_id=actor_user_id,
            action="batch.transition",
            from_status=transition.from_status,
            to_status=transition.to_status,
            metadata_json=metadata or {},
        )
    )
    if to_status in TERMINAL_BATCH_STATUSES:
        event_type = {
            "completed": "batch_completed",
            "failed": "batch_failed",
            "comparison_incomplete": "batch_incomplete",
            "cancelled": "batch_cancelled",
        }[to_status]
        title = {
            "completed": "比对批次已完成",
            "failed": "比对批次执行失败",
            "comparison_incomplete": "比对批次数据不完整",
            "cancelled": "比对批次已取消",
        }[to_status]
        session.add(
            UserNotification(
                user_id=batch.execution_requested_by,
                event_type=event_type,
                batch_id=batch.id,
                run_version=batch.run_version,
                title=title,
                summary_json={
                    "sourceName": batch.source_display_name,
                    "businessType": batch.business_type,
                    "status": to_status,
                },
            )
        )
    await session.commit()
    return batch


async def cancel_batch(
    session: AsyncSession,
    *,
    batch_id: str,
    actor_user_id: int,
    reason: str | None,
) -> ReconciliationBatch:
    batch = await get_batch(session, batch_id)
    if batch.status in TERMINAL_BATCH_STATUSES:
        if batch.status == "cancelled":
            return batch
        raise BatchValidationError("终态批次不能取消。")
    if batch.status not in CANCELLABLE_BATCH_STATUSES:
        raise BatchValidationError("当前阶段不能取消批次。")
    batch.cancellation_requested_at = datetime.now(UTC)
    batch.cancelled_by = actor_user_id
    batch.cancellation_reason = (reason or "").strip() or None
    await transition_batch(
        session,
        batch=batch,
        to_status="cancelling",
        actor_user_id=actor_user_id,
        metadata={"reasonProvided": bool(batch.cancellation_reason)},
    )
    if batch.status == "cancelling":
        await transition_batch(
            session,
            batch=batch,
            to_status="cancelled",
            actor_user_id=actor_user_id,
        )
        batch.cancelled_at = datetime.now(UTC)
        await session.commit()
    return batch


async def rerun_batch(
    session: AsyncSession,
    *,
    batch_id: str,
    actor_user_id: int,
    settings: Settings | None = None,
) -> ReconciliationBatch:
    current_settings = settings or get_settings()
    retention = await get_retention_settings(session, defaults=current_settings)
    previous = await get_batch(session, batch_id)
    if previous.status not in TERMINAL_BATCH_STATUSES:
        raise BatchValidationError("当前执行尚未进入终态，不能创建重新比对版本。")
    source = await session.get(SourceConfig, previous.source_id)
    if source is None or not source.enabled:
        raise BatchValidationError("原批次盘口当前未启用，无法重新比对。")
    latest_version = int(
        await session.scalar(
            select(func.max(ReconciliationBatch.run_version)).where(
                ReconciliationBatch.comparison_series_id == previous.comparison_series_id
            )
        )
        or previous.run_version
    )
    now = datetime.now(UTC)
    rerun = ReconciliationBatch(
        comparison_series_id=previous.comparison_series_id,
        comparison_identity_key=previous.comparison_identity_key,
        run_version=latest_version + 1,
        rerun_of_batch_id=previous.id,
        source_id=source.source_id,
        source_display_name=source.display_name,
        source_config_version=source.config_version,
        source_business_timezone=source.business_timezone,
        source_currency=source.currency,
        business_type=previous.business_type,
        status="awaiting_confirmation",
        uploaded_file_name=previous.uploaded_file_name,
        uploaded_file_sha256=previous.uploaded_file_sha256,
        parameters_json=previous.parameters_json,
        progress_json={"stage": "awaiting_confirmation", "processedRows": 0},
        execution_requested_by=actor_user_id,
        created_by=previous.created_by,
        result_expires_at=now + timedelta(days=retention.result_retention_days),
    )
    session.add(rerun)
    await session.flush()
    previous_reference = await session.scalar(
        select(StoredFileReference).where(
            StoredFileReference.batch_id == previous.id,
            StoredFileReference.expires_at > now,
        )
    )
    if previous_reference is None:
        await session.rollback()
        raise BatchValidationError("原始文件已过期，当前版本尚无规范化快照，请重新上传。")
    session.add(
        StoredFileReference(
            file_object_id=previous_reference.file_object_id,
            batch_id=rerun.id,
            expires_at=now + timedelta(days=retention.uploaded_file_retention_days),
        )
    )
    session.add(
        BatchActivityLog(
            batch_id=rerun.id,
            actor_user_id=actor_user_id,
            action="batch.rerun",
            to_status=rerun.status,
            metadata_json={"rerunOfBatchId": previous.id},
        )
    )
    await session.commit()
    return rerun


async def summarize_batch(session: AsyncSession, batch: ReconciliationBatch) -> dict[str, int]:
    result = await session.execute(
        select(
            OrderReconciliationResult.result_status,
            func.count(OrderReconciliationResult.id),
        )
        .where(OrderReconciliationResult.batch_id == batch.id)
        .group_by(OrderReconciliationResult.result_status)
    )
    counts = {str(status): int(count) for status, count in result.all()}
    counts["confirmed_missing_success"] = int(
        await session.scalar(
            select(func.count())
            .select_from(OrderReconciliationResult)
            .where(
                OrderReconciliationResult.batch_id == batch.id,
                OrderReconciliationResult.result_status == "confirmed_missing",
                OrderReconciliationResult.payment_status_group == "success",
            )
        )
        or 0
    )
    return counts
