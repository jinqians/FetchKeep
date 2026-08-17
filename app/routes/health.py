"""Health-check and application info endpoints.

Both are read-only. Cookies and proxies are server-side configuration in Lite —
these endpoints report whether each platform is configured, never what with, and
there is no counterpart that changes it.
"""

import shutil

from fastapi import APIRouter

from app import parsers
from app.config import MAX_WORKERS, RETENTION_HOURS, SOURCE_URL
from app.cookies import cookie_status
from app.proxy import proxy_coverage

router = APIRouter()


def _status_payload() -> dict:
    yt = shutil.which("yt-dlp") is not None
    gd = shutil.which("gallery-dl") is not None
    ff = shutil.which("ffmpeg") is not None

    cookies = cookie_status()
    proxies = proxy_coverage()

    payload = {
        "status": "ok" if (yt and gd and ff) else "degraded",
        "yt_dlp": yt,
        "gallery_dl": gd,
        "ffmpeg": ff,
        "cookies": cookies,
        "proxies": proxies,
        "parser_chain": parsers.parser_chain_info(),
        "has_external_parser": parsers.has_external_parser(),
        "workers": MAX_WORKERS,
        "retention_hours": RETENTION_HOURS,
        # AGPL-3.0 §13: network users are entitled to this deployment's source.
        "license": "AGPL-3.0",
        "source_url": SOURCE_URL,
    }

    # Flat aliases, kept because the WebUI and any existing monitoring read
    # them by name.
    for platform, configured in proxies.items():
        payload[f"{platform}_proxy_configured"] = configured
    for platform, configured in cookies.items():
        payload[f"{platform}_cookie_configured"] = configured

    return payload


@router.get("/api/health")
def health():
    return _status_payload()


@router.get("/api/info")
def info():
    return _status_payload()
