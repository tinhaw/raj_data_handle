from __future__ import annotations

import asyncio
import time

from redis.asyncio import Redis

from packages.common.security import sha256_text
from packages.common.settings import Settings, get_settings


class LoginRateLimitExceeded(ValueError):
    pass


class LoginRateLimitUnavailable(RuntimeError):
    pass


_fallback_lock = asyncio.Lock()
_fallback_counters: dict[str, tuple[int, float]] = {}


async def _development_fallback(key: str, settings: Settings) -> None:
    now = time.monotonic()
    async with _fallback_lock:
        count, expires_at = _fallback_counters.get(
            key, (0, now + settings.login_rate_limit_window_seconds)
        )
        if now >= expires_at:
            count, expires_at = 0, now + settings.login_rate_limit_window_seconds
        count += 1
        _fallback_counters[key] = (count, expires_at)
        if count > settings.login_rate_limit_max_attempts:
            raise LoginRateLimitExceeded("登录尝试过于频繁，请稍后再试。")


async def check_login_rate_limit(
    *,
    client_ip: str,
    username: str,
    settings: Settings | None = None,
) -> None:
    current_settings = settings or get_settings()
    if not current_settings.login_rate_limit_enabled:
        return
    identity = sha256_text(f"{client_ip}:{username.strip().casefold()}")
    key = f"raj:login-rate:{identity}"
    try:
        redis = Redis.from_url(current_settings.redis_url, decode_responses=True)
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, current_settings.login_rate_limit_window_seconds)
        finally:
            await redis.aclose()
    except Exception as exc:
        if current_settings.is_production:
            raise LoginRateLimitUnavailable("登录限流服务暂不可用。") from exc
        await _development_fallback(key, current_settings)
        return
    if count > current_settings.login_rate_limit_max_attempts:
        raise LoginRateLimitExceeded("登录尝试过于频繁，请稍后再试。")
