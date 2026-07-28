from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RetentionSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    uploaded_file_retention_days: int = Field(alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(alias="remoteCacheRetentionDays")
    session_ttl_days: int = Field(alias="sessionTtlDays")
    config_version: int = Field(alias="configVersion")
    updated_by: int | None = Field(alias="updatedBy")
    updated_at: datetime = Field(alias="updatedAt")


class RetentionSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uploaded_file_retention_days: int = Field(ge=1, le=3650, alias="uploadedFileRetentionDays")
    result_retention_days: int = Field(ge=1, le=3650, alias="resultRetentionDays")
    remote_cache_retention_days: int = Field(ge=1, le=3650, alias="remoteCacheRetentionDays")
    session_ttl_days: int = Field(ge=1, le=365, alias="sessionTtlDays")
