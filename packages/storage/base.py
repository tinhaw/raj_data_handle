from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile


@dataclass(frozen=True, slots=True)
class StoredUpload:
    content_sha256: str
    storage_key: str
    byte_size: int
    content_type: str | None


class FileStorage(Protocol):
    async def store_upload(self, upload: UploadFile) -> StoredUpload: ...

    async def delete(self, storage_key: str) -> None: ...

    def resolve_path(self, storage_key: str) -> Path: ...
