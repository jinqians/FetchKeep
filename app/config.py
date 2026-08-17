"""Centralised configuration: environment variables, paths, and constants."""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------
# Resolved from this file rather than the process's working directory: uvicorn
# can be started from anywhere, and a relative "static" only works when the
# repository root happens to be the CWD.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# The admin console shell lives outside the mounted static directory, so that a
# deployment with no ADMIN_TOKEN cannot serve it at all — /admin 404s and there
# is no /static/admin.html to reach instead.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

DOWNLOAD_ROOT = Path(os.getenv("DOWNLOAD_ROOT", "/data/downloads"))
COOKIES_DIR = Path(os.getenv("COOKIES_DIR", "/data/cookies"))
COOKIE_FILE = Path(os.getenv("COOKIE_FILE", str(COOKIES_DIR / "cookies.txt")))


def _cookie_path(platform: str) -> Path:
    """Where one platform's cookies.txt lives.

    ``<PLATFORM>_COOKIE_FILE`` lets an operator point at a file mounted
    somewhere else entirely — a read-only secret, a path shared with another
    container — instead of having to land it inside COOKIES_DIR. Unset, the
    default is the file this app would have written anyway.
    """
    override = (os.getenv(f"{platform.upper()}_COOKIE_FILE") or "").strip()
    return Path(override) if override else COOKIES_DIR / f"{platform}.txt"


# Platform-specific cookie files.
INSTAGRAM_COOKIE_FILE = _cookie_path("instagram")
YOUTUBE_COOKIE_FILE = _cookie_path("youtube")
TIKTOK_COOKIE_FILE = _cookie_path("tiktok")
DOUYIN_COOKIE_FILE = _cookie_path("douyin")
BILIBILI_COOKIE_FILE = _cookie_path("bilibili")

# Every platform whose cookies the operator can configure. Douyin in particular
# refuses its web detail JSON without a fresh cookie jar, even for public videos
# and without being logged in.
#
# Bilibili is the other kind of case: anonymous access works, but it is capped
# at 480p. The cookie jar (SESSDATA) is what unlocks 1080p and above, so an
# empty one here is a quality ceiling rather than a failure.
COOKIE_FILES = {
    "instagram": INSTAGRAM_COOKIE_FILE,
    "youtube": YOUTUBE_COOKIE_FILE,
    "tiktok": TIKTOK_COOKIE_FILE,
    "douyin": DOUYIN_COOKIE_FILE,
    "bilibili": BILIBILI_COOKIE_FILE,
}

# Cookies are server-side configuration in Lite: there is no upload endpoint and
# no WebUI for them. Besides mounting the files, an operator can inline the jar
# in the environment — `<PLATFORM>_COOKIES`, raw or base64 — and app.cookies
# materialises it into COOKIE_FILES at startup.
COOKIE_ENV_VARS = {name: f"{name.upper()}_COOKIES" for name in COOKIE_FILES}

# ---------------------------------------------------------------------------
# Platform proxies (optional, empty ⇒ direct VPS egress)
# ---------------------------------------------------------------------------
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY", "").strip()
TWITTER_PROXY = os.getenv("TWITTER_PROXY", "").strip()
TIKTOK_PROXY = os.getenv("TIKTOK_PROXY", "").strip()
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "").strip()
DOUYIN_PROXY = os.getenv("DOUYIN_PROXY", "").strip()
BILIBILI_PROXY = os.getenv("BILIBILI_PROXY", "").strip()

# ---------------------------------------------------------------------------
# Source offer (AGPL-3.0 §13)
# ---------------------------------------------------------------------------
# This program is network-facing and licensed under the AGPL, which means every
# user who interacts with it over a network is entitled to *this deployment's*
# source — including your modifications, not just upstream's. Point this at the
# repository the running code actually came from; the footer links to it.
SOURCE_URL = (os.getenv("SOURCE_URL") or "").strip()

# ---------------------------------------------------------------------------
# Worker / retention settings
# ---------------------------------------------------------------------------
MAX_WORKERS = max(1, int(os.getenv("MAX_WORKERS", "2")))
RETENTION_HOURS = max(1, int(os.getenv("JOB_RETENTION_HOURS", "24")))

# Without this yt-dlp waits on a silent socket far longer than anyone watching a
# progress bar will. --retries covers the transient half.
YTDLP_SOCKET_TIMEOUT = max(5, int(os.getenv("YTDLP_SOCKET_TIMEOUT", "30")))

# ---------------------------------------------------------------------------
# Directory bootstrapping
# ---------------------------------------------------------------------------
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
COOKIES_DIR.mkdir(parents=True, exist_ok=True)
COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# yt-dlp output template
# ---------------------------------------------------------------------------
# Limit the title portion of the filename so long CJK titles cannot exceed
# Linux NAME_MAX (255 bytes).
OUTPUT_TEMPLATE = "%(title).80s [%(id)s].%(ext)s"

# Used both for the header-based platforms (Bilibili) and for the parser chain's
# direct-link fallback, which talks to a CDN that checks the same things.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Quality constants
# ---------------------------------------------------------------------------
# "compat" caps at AVC/AAC so the result always plays in the browser without
# post-processing. YouTube only offers AVC up to 1080p, so anything higher
# necessarily means VP9/AV1.
QUALITY_COMPAT = "compat"
QUALITY_BEST = "best"
QUALITY_AUDIO = "audio"

# ---------------------------------------------------------------------------
# Browser-playable codec / container sets
# ---------------------------------------------------------------------------
BROWSER_VIDEO_CODECS = {"h264", "vp8", "vp9", "av01"}
BROWSER_AUDIO_CODECS = {"aac", "mp4a", "opus", "vorbis", "mp3", ""}
BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}

# ---------------------------------------------------------------------------
# File-type suffix sets
# ---------------------------------------------------------------------------
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v", ".mkv"}
AUDIO_SUFFIXES = {".m4a", ".mp3", ".opus", ".aac", ".wav", ".flac", ".ogg"}

# What a download tool leaves behind when it dies mid-transfer. These are not
# results, and the difference matters more than it looks: "did this run produce
# files?" is the question every fallback turns on, and a 3 MB `.part` from a
# connection that dropped answers it "yes" — the fallback is skipped and the
# user is handed a truncated video that plays for four seconds.
PARTIAL_SUFFIXES = {".part", ".ytdl", ".tmp", ".temp", ".download", ".crdownload"}

# A response this small is not a video. Douyin's CDN answers a rejected request
# with a short JSON or HTML body under HTTP 200, and without a floor that page
# gets written to disk as an .mp4, counted as the job's output and published.
MIN_MEDIA_BYTES = 64 * 1024

# Directory inside a job folder for generated archives. Excluded from the file
# listing so a ZIP the user asked for does not come back as a job "result".
ARCHIVE_DIRNAME = ".archives"

# ---------------------------------------------------------------------------
# MIME-type mapping for inline serving
# ---------------------------------------------------------------------------
MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".m4v": "video/x-m4v", ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".opus": "audio/opus",
    ".aac": "audio/aac", ".wav": "audio/wav", ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}
