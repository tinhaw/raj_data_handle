#!/usr/bin/env python3
"""Create the local-only RajLuck production secrets file without printing keys."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import tempfile
from pathlib import Path


class SecretFileError(RuntimeError):
    """Raised for unsafe local secret-file input."""


def build_secrets_file() -> str:
    encryption_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    return "\n".join(
        (
            "# Generated locally. Do not commit this file or paste its values into chat/logs.",
            "RAJ_RDS_USERNAME=",
            "RAJ_RDS_PASSWORD=",
            f"RAJ_SECRET_KEY={secrets.token_urlsafe(48)}",
            f"RAJ_CREDENTIAL_ENCRYPTION_KEY={encryption_key}",
            "RAJ_UPLOAD_MAX_BYTES=52428800",
            "RAJ_UPLOADED_FILE_RETENTION_DAYS=3",
            "RAJ_RESULT_RETENTION_DAYS=30",
            "RAJ_REMOTE_CACHE_RETENTION_DAYS=30",
            "",
        )
    )


def write_secrets_file(path: Path, content: str, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise SecretFileError(f"refusing to overwrite existing secrets file: {path}")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create local RajLuck production secrets without printing them."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[1] / "deploy/secrets/raj-data-handle.env",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing local secrets file.",
    )
    args = parser.parse_args()

    try:
        write_secrets_file(
            args.output,
            build_secrets_file(),
            force=args.force,
        )
    except SecretFileError as exc:
        parser.exit(2, f"init_rajluck_secrets: {exc}\n")

    print(json.dumps({"output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
