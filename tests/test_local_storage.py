import hashlib
from io import BytesIO

import pytest
from fastapi import UploadFile

from packages.storage.local import LocalFileStorage, UploadTooLargeError


@pytest.mark.asyncio
async def test_content_addressed_upload_is_deduplicated(tmp_path) -> None:
    content = b"same payment export"
    storage = LocalFileStorage(tmp_path, max_bytes=1024)
    first = await storage.store_upload(UploadFile(filename="one.csv", file=BytesIO(content)))
    second = await storage.store_upload(UploadFile(filename="two.csv", file=BytesIO(content)))

    assert first.content_sha256 == hashlib.sha256(content).hexdigest()
    assert second.storage_key == first.storage_key
    assert len(list(tmp_path.rglob(first.content_sha256))) == 1


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_without_leaving_file(tmp_path) -> None:
    storage = LocalFileStorage(tmp_path, max_bytes=4)
    with pytest.raises(UploadTooLargeError):
        await storage.store_upload(UploadFile(filename="large.csv", file=BytesIO(b"12345")))
    assert list(tmp_path.rglob("upload-*")) == []
