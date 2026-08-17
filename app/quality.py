"""Quality parsing, yt-dlp format selectors, and remote quality probing."""

import json
import re
import subprocess

from app.config import (
    BROWSER_UA,
    OUTPUT_TEMPLATE,
    QUALITY_AUDIO,
    QUALITY_BEST,
    QUALITY_COMPAT,
    YTDLP_SOCKET_TIMEOUT,
)
from app.cookies import cookie_args_for
from app.platform import (
    is_bilibili,
    is_douyin,
    is_instagram,
    is_tiktok,
    is_youtube,
)
from app.proxy import proxy_args_for


# ── Quality parsing ─────────────────────────────────────────────────────────

def parse_quality(quality: str) -> str:
    """Normalize a requested quality into 'compat', 'best', 'audio' or a height."""
    value = (quality or QUALITY_COMPAT).strip().lower()
    if value in {"", "auto", QUALITY_COMPAT}:
        return QUALITY_COMPAT
    if value in {QUALITY_BEST, QUALITY_AUDIO}:
        return value
    if re.fullmatch(r"\d{3,4}", value):
        return value
    return QUALITY_COMPAT


# ── Platform-specific yt-dlp arguments ──────────────────────────────────────

def yt_dlp_impersonate_args(url: str) -> list[str]:
    """Browser TLS/HTTP impersonation, for the sites that fingerprint it.

    These sites answer with an empty body when the client does not look like a
    real browser. Impersonation is not a substitute for cookies on Douyin, but
    the two are needed together.

    Bilibili is deliberately left out. Its extractor signs its own API requests
    (WBI) and a plain request works — the 412s it returns under load are rate
    limiting, not a fingerprint check.
    """
    if is_instagram(url) or is_douyin(url) or is_tiktok(url):
        return ["--impersonate", "chrome"]
    return []


def yt_dlp_site_args(url: str) -> list[str]:
    """Per-site request arguments, for every way this app invokes yt-dlp.

    The Referer is Bilibili's documented requirement for its web APIs and costs
    nothing to send. It is **not** what fixes the HTTP 412 those APIs return
    under load — that is rate limiting, and no header combination avoids it.

    YouTube and everything else get nothing: not forcing a curl_cffi
    impersonation target is what keeps yt-dlp on its normal request handler
    instead of failing when a particular target is missing from the build.
    """
    if is_bilibili(url):
        return [
            "--add-header", "Referer:https://www.bilibili.com/",
            "--user-agent", BROWSER_UA,
        ]
    return []


def yt_dlp_download_args(url: str, quality: str, job_dir) -> list[str]:
    """The arguments shared by every way of invoking yt-dlp for a download."""
    return [
        "--no-mtime",
        "-P", str(job_dir),
        "--no-playlist",
        # Without this yt-dlp waits on a silent socket far longer than anyone
        # watching a progress bar will. --retries covers the transient half.
        "--socket-timeout", str(YTDLP_SOCKET_TIMEOUT),
        "--retries", "3",
        *yt_dlp_common_args(url, quality),
        *yt_dlp_site_args(url),
        *yt_dlp_impersonate_args(url),
    ]


def yt_dlp_common_args(url: str, quality: str = QUALITY_COMPAT) -> list[str]:
    """Build the yt-dlp format-selection arguments for *url* and *quality*."""
    quality = parse_quality(quality)
    out = ["-o", OUTPUT_TEMPLATE]

    if quality == QUALITY_AUDIO:
        return ["-f", "ba[ext=m4a]/ba/b", "-x", "--audio-format", "m4a", *out]

    if is_tiktok(url) or is_douyin(url):
        # TikTok/Douyin already serve a single pre-muxed (video+audio) stream,
        # so grab the best whole format directly instead of picking separate
        # video/audio streams. This avoids any ffmpeg merge without costing
        # quality in practice.
        if quality in {QUALITY_COMPAT, QUALITY_BEST}:
            return ["-f", "b", *out]
        return ["-f", f"b[height<={quality}]/b", *out]

    if is_bilibili(url):
        # Bilibili is pure DASH: the probe returns video-only and audio-only
        # streams and *zero* muxed ones, so the Douyin branch above (`-f b`,
        # "grab the single pre-muxed stream") has nothing to select and would
        # fail outright. Video and audio must be merged.
        #
        # The codec filter is not optional either. Bilibili serves hev1 (H.265)
        # alongside avc1, and a browser cannot play hev1 inline — without the
        # preference a 1080p download lands as a file the user can only save,
        # never preview. avc1 first, anything second, so an odd video that only
        # exists in H.265 still downloads.
        if quality == QUALITY_BEST:
            selector = "bv*+ba/b"
        else:
            height = "" if quality == QUALITY_COMPAT else f"[height<={quality}]"
            selector = (
                f"bv*{height}[vcodec^=avc1]+ba/"
                f"bv*{height}+ba/"
                f"b{height}/b"
            )
        return ["-f", selector, "--merge-output-format", "mp4", *out]

    if is_youtube(url) or quality != QUALITY_COMPAT:
        if quality == QUALITY_COMPAT:
            # AVC video + AAC audio only: always browser-playable, but YouTube
            # caps AVC at 1080p so this cannot reach 1440p/2160p.
            selector = (
                "bv*[vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/"
                "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/"
                "b[ext=mp4][vcodec^=avc1]"
            )
        elif quality == QUALITY_BEST:
            selector = "bv*+ba/b"
        else:
            # Prefer AVC at the requested height so no transcode is needed,
            # then fall back to whatever codec exists at that height.
            selector = (
                f"bv*[height<={quality}][vcodec^=avc1]+ba[acodec^=mp4a]/"
                f"bv*[height<={quality}]+ba/"
                f"b[height<={quality}]/b"
            )
        return ["-f", selector, "--merge-output-format", "mp4", *out]

    return []


# ── Remote quality probing ──────────────────────────────────────────────────

def _format_size(fmt: dict, duration: float) -> int | None:
    """Best-effort byte size for a yt-dlp format entry."""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        return int(size)
    tbr = fmt.get("tbr")
    if tbr and duration:
        return int(tbr * 1000 / 8 * duration)
    return None


def probe_formats(url: str) -> dict:
    """Ask yt-dlp which qualities actually exist for this URL."""
    cmd = [
        "yt-dlp", "-J", "--no-playlist", "--no-warnings",
        "--socket-timeout", str(YTDLP_SOCKET_TIMEOUT),
        *yt_dlp_site_args(url),
        *yt_dlp_impersonate_args(url),
        *cookie_args_for(url),
        *proxy_args_for(url),
        url,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("获取画质列表超时，请稍后重试或检查代理设置")

    if proc.returncode != 0 or not proc.stdout.strip():
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(tail or "无法获取该链接的可用画质")

    data = json.loads(proc.stdout)
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if e]
        if not entries:
            raise RuntimeError("该链接没有可下载的视频")
        data = entries[0]

    duration = data.get("duration") or 0
    formats = data.get("formats") or []

    # Best audio-only stream: needed to estimate the size of a merged download.
    audio_only = [
        f for f in formats
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
    ]
    best_audio = max(
        audio_only, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None
    )
    audio_size = _format_size(best_audio, duration) if best_audio else None

    # Keep one representative format per resolution, preferring AVC so the
    # download needs no transcode to stay browser-playable.
    by_height: dict = {}
    for f in formats:
        vcodec = f.get("vcodec")
        height = f.get("height")
        if not height or vcodec in (None, "none"):
            continue
        score = (1 if str(vcodec).startswith("avc1") else 0, f.get("tbr") or 0)
        if height not in by_height or score > by_height[height][0]:
            by_height[height] = (score, f)

    options = []
    for height, (_score, f) in sorted(by_height.items(), key=lambda kv: -kv[0]):
        muxed = f.get("acodec") not in (None, "none")
        size = _format_size(f, duration)
        if size is not None and not muxed and audio_size:
            size += audio_size
        vcodec = (f.get("vcodec") or "").split(".")[0]
        suffix = " (4K)" if height >= 2160 else " (2K)" if height >= 1440 else ""
        options.append({
            "quality": str(height),
            "label": f"{height}p{suffix}",
            "height": height,
            "fps": f.get("fps"),
            "vcodec": vcodec,
            "ext": "mp4",
            "filesize": size,
            "needs_merge": not muxed,
            "browser_playable": vcodec in {"avc1", "h264", "vp9", "vp09", "av01"},
        })

    if best_audio:
        options.append({
            "quality": QUALITY_AUDIO,
            "label": "仅音频",
            "height": None,
            "fps": None,
            "vcodec": None,
            "ext": "m4a",
            "filesize": audio_size,
            "needs_merge": False,
            "browser_playable": True,
        })

    return {
        "supported": True,
        "title": data.get("title") or "",
        "duration": duration,
        "formats": options,
    }
