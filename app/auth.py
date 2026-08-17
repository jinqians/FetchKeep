"""Admin authentication for the console.

Lite is a passwordless public deployment: anyone who can reach the download page
can use it. That is the whole design, and it is exactly why the console cannot
inherit it — the console uploads cookie jars, lists every job's URL, and deletes
files. So the rule here is the opposite of the rest of the app:

    **No ADMIN_TOKEN, no console.** Not "open by default", not "warn and allow" —
    every admin route 404s until a token is configured.

Pro can default the console open because it sits behind an identity provider and
a single operator; Lite has neither, and a console that is reachable by default
on a public URL is a cookie-jar upload form for the internet.

The token travels in an `x-admin-token` header, not a cookie: a custom header
cannot be attached by a cross-site form or image, so CSRF needs no separate
defence. The browser keeps it in sessionStorage, so closing the tab ends it.
"""

import asyncio
import hmac
import os
import threading
import time

from fastapi import HTTPException, Request

from app.config import SOURCE_URL

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or "").strip()
ADMIN_TOKEN_HEADER = "x-admin-token"

# A shared secret on a public URL gets guessed at. Rather than locking an IP out
# — which lets anyone behind the same reverse proxy lock the real operator out —
# each failure just makes the next answer slower. Brute force dies on the delay;
# the operator who mistypes once waits a quarter second.
_MAX_DELAY_SECONDS = 4.0
_FAILURE_TTL_SECONDS = 900

_failures: dict[str, tuple[int, float]] = {}
_failures_lock = threading.Lock()

# Short enough to be guessed. Not refused — an operator who sets a weak token and
# gets an unexplained 404 has no way to find out why — but the console is told,
# and it says so on every page load.
MIN_RECOMMENDED_TOKEN_LENGTH = 16


def admin_enabled() -> bool:
    """Whether an admin token is configured at all."""
    return bool(ADMIN_TOKEN)


def token_is_weak() -> bool:
    return admin_enabled() and len(ADMIN_TOKEN) < MIN_RECOMMENDED_TOKEN_LENGTH


def _client_key(request: Request) -> str:
    """Bucket key for the failure delay.

    Deliberately the socket peer, not X-Forwarded-For: that header is attacker
    supplied, and honouring it would let one client present a fresh address on
    every attempt and never be slowed down at all. Behind a reverse proxy every
    caller shares one bucket, which only makes the delay stricter — and since
    the penalty is latency rather than a lockout, stricter is safe.
    """
    return request.client.host if request.client else "unknown"


def _record_failure(key: str) -> float:
    """Count a failed attempt and return how long the answer should be delayed."""
    now = time.monotonic()
    with _failures_lock:
        # Drop stale buckets here rather than on a timer: this runs only on
        # failures, so the dict cannot grow without someone guessing at it.
        for stale in [k for k, (_, seen) in _failures.items()
                      if now - seen > _FAILURE_TTL_SECONDS]:
            del _failures[stale]

        count, last_seen = _failures.get(key, (0, now))
        if now - last_seen > _FAILURE_TTL_SECONDS:
            count = 0
        count += 1
        _failures[key] = (count, now)

    return min(0.25 * (2 ** (count - 1)), _MAX_DELAY_SECONDS)


def _clear_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)


async def require_admin(request: Request) -> None:
    """FastAPI dependency: reject anyone without the admin token.

    404 rather than 401 when no token is configured, so a deployment that never
    set one does not advertise a console it cannot let anyone into.
    """
    if not admin_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    supplied = request.headers.get(ADMIN_TOKEN_HEADER, "")
    key = _client_key(request)

    if supplied and hmac.compare_digest(supplied, ADMIN_TOKEN):
        _clear_failures(key)
        return

    delay = _record_failure(key)
    await asyncio.sleep(delay)
    raise HTTPException(status_code=401, detail="口令不正确")


def startup_banner() -> None:
    """Say, once, what state the console is in."""
    # Not an admin concern, but it belongs in the same one-time boot report: a
    # public AGPL deployment owes its users a source offer, and an operator who
    # never set SOURCE_URL has no other way to find that out.
    if not SOURCE_URL:
        print(
            "[license] 未设置 SOURCE_URL，页脚不会显示源码链接。"
            "AGPL-3.0 §13 要求通过网络使用本程序的用户能拿到本部署的源码"
            "（含你的修改），公开部署请设置它。",
            flush=True,
        )

    if not admin_enabled():
        print(
            "[admin] 未设置 ADMIN_TOKEN，管理后台已关闭（/admin 返回 404）。"
            "需要后台请在 .env 里设置 ADMIN_TOKEN 后重启。",
            flush=True,
        )
        return

    if token_is_weak():
        print(
            f"[admin] 警告：ADMIN_TOKEN 只有 {len(ADMIN_TOKEN)} 位，"
            f"建议至少 {MIN_RECOMMENDED_TOKEN_LENGTH} 位随机字符。"
            "生成一个：openssl rand -base64 24",
            flush=True,
        )
    print("[admin] 管理后台已启用: /admin", flush=True)
