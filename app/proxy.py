"""Proxy argument construction for each supported platform."""

from typing import Optional

from app.config import (
    BILIBILI_PROXY,
    DOUYIN_PROXY,
    INSTAGRAM_PROXY,
    TIKTOK_PROXY,
    TWITTER_PROXY,
    YOUTUBE_PROXY,
)
from app.platform import platform_slug_for

# Proxies are optional and platform-specific.
# An empty value means direct VPS egress.
PLATFORM_PROXIES = {
    "instagram": INSTAGRAM_PROXY,
    "twitter": TWITTER_PROXY,
    "tiktok": TIKTOK_PROXY,
    "youtube": YOUTUBE_PROXY,
    "douyin": DOUYIN_PROXY,
    "bilibili": BILIBILI_PROXY,
}


def proxy_for(url: str) -> str:
    """The proxy URL configured for the platform behind *url*, or ""."""
    return PLATFORM_PROXIES.get(platform_slug_for(url), "")


def proxy_args_for(url: str) -> list[str]:
    """Return ``['--proxy', '<url>']`` when a proxy is configured."""
    proxy = proxy_for(url)
    return ["--proxy", proxy] if proxy else []


def proxy_configured_for(url: str) -> bool:
    """Check whether a proxy has been set for the platform behind *url*."""
    return bool(proxy_for(url))


def proxy_coverage() -> dict[str, bool]:
    """Which platforms currently have an exit configured."""
    return {name: bool(value) for name, value in PLATFORM_PROXIES.items()}


def proxy_url_from_args(proxy_args) -> Optional[str]:
    """The proxy URL out of a yt-dlp argument list, for the non-yt-dlp paths."""
    args = list(proxy_args or [])
    for i in range(len(args) - 1):
        if args[i] == "--proxy":
            return args[i + 1] or None
    return None
