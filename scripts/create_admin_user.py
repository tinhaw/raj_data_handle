from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import func, select

from packages.common.database import AsyncSessionLocal
from packages.domain.models import AppUser
from packages.domain.services.auth_service import AuthError, create_user


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first Raj Data Handle administrator.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read one password line from stdin instead of an interactive hidden prompt.",
    )
    return parser.parse_args()


def read_password(use_stdin: bool) -> str:
    if use_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("管理员密码: ")
    second = getpass.getpass("再次输入密码: ")
    if first != second:
        raise SystemExit("两次输入的密码不一致。")
    return first


async def run(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        active_admin_count = await session.scalar(
            select(func.count())
            .select_from(AppUser)
            .where(AppUser.role == "admin", AppUser.is_active.is_(True))
        )
        if active_admin_count:
            raise SystemExit("系统已存在有效管理员，拒绝重复执行引导命令。")
        try:
            user = await create_user(
                session,
                username=args.username,
                password=read_password(args.password_stdin),
                display_name=args.display_name or args.username,
                role="admin",
                actor_user_id=None,
            )
        except AuthError as exc:
            raise SystemExit(str(exc)) from exc
    print(f"管理员已创建：{user.username}")


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
