"""Platform detection helpers and download-engine selection."""

import re


def is_instagram(url: str) -> bool:
    return bool(re.search(r"https?://(?:www\.)?instagram\.com/", url, re.I))


def is_x(url: str) -> bool:
    return bool(re.search(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/", url, re.I))


def is_tiktok(url: str) -> bool:
    return bool(re.search(r"https?://(?:(?:www|vm|vt)\.)?tiktok\.com/", url, re.I))


def is_youtube(url: str) -> bool:
    return bool(re.search(
        r"https?://(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/",
        url, re.I,
    ))


def is_douyin(url: str) -> bool:
    return bool(re.search(
        r"https?://(?:(?:www)\.)?(?:douyin\.com|v\.douyin\.com)/",
        url, re.I,
    ))


def is_bilibili(url: str) -> bool:
    # b23.tv is the share shortener; it appears in every link copied out of the
    # mobile app, so a matcher that only knows bilibili.com misses the common case.
    return bool(re.search(
        r"https?://(?:(?:www|m|space|live)\.)?(?:bilibili\.com|b23\.tv)/",
        url, re.I,
    ))


def platform_slug_for(url: str) -> str:
    """The machine-readable platform name, as used by proxies and cookies.

    Kept separate from platform_name_for: that one produces display text, and
    routing a download on a display string is how you get a proxy that works in
    Chinese and not in English.
    """
    if is_instagram(url):
        return "instagram"
    if is_x(url):
        return "twitter"
    if is_tiktok(url):
        return "tiktok"
    if is_youtube(url):
        return "youtube"
    if is_douyin(url):
        return "douyin"
    if is_bilibili(url):
        return "bilibili"
    return ""


def platform_name_for(url: str) -> str:
    """Display name of the platform behind *url*, for user-facing messages."""
    return {
        "instagram": "Instagram",
        "twitter": "X / Twitter",
        "tiktok": "TikTok",
        "youtube": "YouTube",
        "douyin": "抖音",
        "bilibili": "哔哩哔哩",
    }.get(platform_slug_for(url), "目标站点")


def detect_engine(url: str) -> str:
    """Choose the primary download engine for *url*."""
    if is_instagram(url):
        path = url.lower().split("?", 1)[0]
        if "/reel/" in path or "/reels/" in path or "/tv/" in path:
            return "yt-dlp"
        return "gallery-dl"

    if is_x(url):
        return "gallery-dl"

    return "yt-dlp"
