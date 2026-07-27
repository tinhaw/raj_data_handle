from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import UploadFile

from packages.storage.base import StoredUpload


class UploadTooLargeError(ValueError):
    pass


class LocalFileStorage:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    async def store_upload(self, upload: UploadFile) -> StoredUpload:
        digest = hashlib.sha256()
        total = 0
        file_descriptor, temporary_name = tempfile.mkstemp(prefix="upload-", dir=self.root)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise UploadTooLargeError(
                            f"文件超过 {self.max_bytes // (1024 * 1024)} MB 限制。"
                        )
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            content_sha256 = digest.hexdigest()
            relative_key = f"{content_sha256[:2]}/{content_sha256}"
            final_path = self._resolve(relative_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if final_path.exists():
                temporary_path.unlink(missing_ok=True)
            else:
                os.replace(temporary_path, final_path)
            return StoredUpload(
                content_sha256=content_sha256,
                storage_key=relative_key,
                byte_size=total,
                content_type=upload.content_type,
            )
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.seek(0)

    async def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    def resolve_path(self, storage_key: str) -> Path:
        return self._resolve(storage_key)

    def _resolve(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("非法存储路径。")
        return candidate
