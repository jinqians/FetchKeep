"""Third-party video parsers for Douyin and TikTok.

yt-dlp's Douyin extractor breaks frequently — the platform's X-Bogus / A_Bogus
signature rotation, TLS fingerprinting and aggressive cookie staleness checks
outpace yt-dlp's release cycle.  This module sits *in front of* yt-dlp: if a
configured parser can resolve the video's direct URL, the download bypasses the
fragile extraction entirely; if every parser fails, yt-dlp still gets its turn.

Architecture
────────────
    URL  →  ParserChain  →  first success  →  direct HTTP download
                │                                      │
                └── all fail ──────────────────────── yt-dlp (fallback)

Three back-ends are supported, mixed freely via environment variables:

  1. Self-hosted API   DOUYIN_PARSER_URL   (Evil0ctal/Douyin_TikTok_Download_API
                                            or any compatible endpoint)
  2. TikHub.io         TIKHUB_API_KEY      (paid, ≈ $0.001/request)
  3. yt-dlp metadata   (always available)   Wraps the existing `-J` probe.

Configuration
─────────────
    # .env
    DOUYIN_PARSER_URL=http://douyin-parser:8000
    TIKHUB_API_KEY=sk-abc123
    PARSER_PRIORITY=self_hosted,tikhub,ytdlp   # optional; default order shown
    PARSER_TIMEOUT=15                          # per-parser HTTP timeout

Listing ytdlp in PARSER_PRIORITY is optional: leave it out and the chain
contains only the third-party parsers. That does *not* disable yt-dlp for
downloads — the caller falls back to a full yt-dlp run whenever the chain comes
up empty — it only stops yt-dlp from being asked for metadata twice.
"""

import ipaddress
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from app.platform import is_douyin, is_tiktok


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ParserResult:
    """What a successful parse produces."""
    video_url: str                    # direct download link (no watermark)
    title: str = ""
    author: str = ""
    cover_url: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    extra: dict = field(default_factory=dict)  # parser-specific metadata

    @property
    def filename(self) -> str:
        """Best-effort filename from the metadata.

        The title is attacker-influenced text on its way to becoming a path, so
        the cleaning is deliberately blunt: path separators and the Windows
        reserved set become "_", control characters and newlines are dropped
        outright, and a leading dot cannot survive (a title starting with "."
        would otherwise produce a hidden file, or worse, "..").

        `%` is left alone on purpose. It is legal in a filename, and escaping it
        for yt-dlp's output template is the caller's job — doing it here would
        put a literal "%%" in the name the HTTP fallback writes.
        """
        stem = "".join(
            ch for ch in (self.title or "") if ch.isprintable()
        )
        for ch in r'\/:*?"<>|':
            stem = stem.replace(ch, "_")
        stem = stem.strip().strip(".").strip()

        # NAME_MAX is 255 *bytes*, and a CJK title spends three of them per
        # character — 80 characters is already 240, and yt-dlp still wants room
        # for its own suffixes. Truncate on the byte count, not the character
        # count, and cut back to a whole character.
        encoded = stem.encode("utf-8")[:180]
        stem = encoded.decode("utf-8", "ignore").strip()

        return f"{stem or 'video'}{self.ext}"

    @property
    def ext(self) -> str:
        """Container suffix, guessed from the resolved URL. Defaults to .mp4."""
        path = urlsplit(self.video_url or "").path.lower()
        for suffix in (".mp4", ".webm", ".mov", ".m4v", ".mkv", ".m4a", ".mp3"):
            if path.endswith(suffix):
                return suffix
        return ".mp4"


# ---------------------------------------------------------------------------
# Shared extraction helpers
# ---------------------------------------------------------------------------

def _first_url(container, key: str = "url_list") -> str:
    """First entry of a `{key: [...]}` list, tolerating every way it can be absent.

    Douyin's payloads put every URL behind a list of mirrors, and an empty list
    is a perfectly ordinary response for a video that has been taken down. The
    naive `container[key][0]` turns that into an IndexError, which reaches the
    user as "list index out of range" instead of a sentence about the video.
    """
    if not isinstance(container, dict):
        return ""
    items = container.get(key)
    if not isinstance(items, list):
        return ""
    for item in items:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _validate_media_url(url: str) -> str:
    """Reject a resolved URL that points somewhere we must not fetch.

    The parsers hand back a URL that this process then requests, so a parser
    that is compromised, misconfigured or simply pointed at the wrong host can
    aim that request at the machine's own network — the container's admin port,
    a metadata endpoint, another service on the compose network.

    Only literal addresses are checked. Resolving the hostname here would add a
    DNS round trip to every download and still not be authoritative, because the
    name can resolve differently when the download actually runs. This blocks
    the careless case, not a determined DNS rebind.
    """
    parsed = urlsplit(url or "")
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError(f"解析结果不是 http(s) 链接: {url[:80]}")

    host = (parsed.hostname or "").strip("[]")
    if not host:
        raise RuntimeError("解析结果缺少主机名")

    low = host.lower()
    if low == "localhost" or low.endswith(".localhost") or low.endswith(".local"):
        raise RuntimeError(f"解析结果指向本机: {host}")

    try:
        ip = ipaddress.ip_address(low)
    except ValueError:
        return url  # A name, not a literal address — allowed.

    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise RuntimeError(f"解析结果指向内网地址: {host}")
    return url


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseParser:
    """Interface every parser implements."""

    name: str = "base"

    def can_handle(self, url: str) -> bool:
        """Whether this parser is willing to try *url*."""
        raise NotImplementedError

    def parse(self, url: str, proxy: Optional[str] = None) -> ParserResult:
        """Resolve *url* into a ParserResult.

        Raises on failure — the caller catches and tries the next parser.
        *proxy* is an optional HTTP/SOCKS proxy URL for the outgoing request.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Self-hosted API  (Evil0ctal/Douyin_TikTok_Download_API compatible)
# ---------------------------------------------------------------------------

class SelfHostedParser(BaseParser):
    """Calls a self-hosted Douyin/TikTok parsing API.

    There is no single response shape to code against. Evil0ctal's API alone has
    two that matter, and neither puts the video URL where a flat lookup would
    find it:

        # v4  /api/hybrid/video_data — `data` *is* the raw aweme detail
        {"code": 200, "data": {"desc": "…", "author": {…},
                               "video": {"play_addr": {"url_list": ["https://…"]},
                                         "duration": 15200}}}

        # v3  /api?url=… — the no-watermark links sit under `video_data`
        {"status": "success",
         "video_data": {"nwm_video_url_HQ": "https://…",
                        "nwm_video_url": "https://…"}}

    Compatible third-party endpoints add more variations still, so extraction
    walks the known locations in order of preference rather than assuming one.
    """

    name = "self_hosted"

    def __init__(self, base_url: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def can_handle(self, url: str) -> bool:
        return True  # The self-hosted API supports both Douyin and TikTok.

    def parse(self, url: str, proxy: Optional[str] = None) -> ParserResult:
        import requests
        proxies = {"http": proxy, "https": proxy} if proxy else None

        # Evil0ctal's API endpoint — try the newer /api/hybrid/video_data first,
        # then fall back to the older /api?url=… shape.
        endpoints = [
            f"{self.base_url}/api/hybrid/video_data",
            f"{self.base_url}/api",
        ]

        last_exc: Optional[Exception] = None
        for endpoint in endpoints:
            try:
                resp = requests.get(
                    endpoint,
                    params={"url": url, "minimal": "false"},
                    timeout=self.timeout,
                    proxies=proxies,
                )
                resp.raise_for_status()
                body = resp.json()
                # Parsing has to be inside the loop. A 200 whose body carries an
                # application-level error is the *normal* failure for these APIs,
                # and treating it as fatal would mean the second endpoint — the
                # whole reason there is a list — never gets tried.
                return self._to_result(body)
            except Exception as exc:
                last_exc = exc
                continue

        raise RuntimeError(
            f"Self-hosted parser at {self.base_url} failed: {last_exc}"
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _to_result(body: dict) -> ParserResult:
        """Normalise the varying JSON shapes into a ParserResult."""
        if not isinstance(body, dict):
            raise RuntimeError("Parser response is not a JSON object")

        # An application-level failure arrives as HTTP 200 with a code in the
        # body, so it has to be read before anything is extracted — otherwise
        # the user gets "no video URL" instead of the reason the API gave.
        code = body.get("code")
        if code is not None and int(code) not in (0, 200):
            msg = body.get("message") or body.get("msg") or body.get("detail")
            raise RuntimeError(f"Parser returned code {code}: {msg or 'unknown error'}")
        status = str(body.get("status") or "").lower()
        if status and status not in ("success", "ok", "200"):
            msg = body.get("message") or body.get("msg") or status
            raise RuntimeError(f"Parser returned status {status}: {msg}")

        # The payload may be wrapped in "data", or returned at the top level.
        data = body.get("data")
        if not isinstance(data, dict):
            data = body

        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        video_data = (
            data.get("video_data")
            if isinstance(data.get("video_data"), dict)
            else {}
        )

        video_url = (
            # v3 / legacy: explicit no-watermark links, best quality first.
            video_data.get("nwm_video_url_HQ")
            or video_data.get("nwm_video_url")
            or data.get("nwm_video_url_HQ")
            or data.get("nwm_video_url")
            # v4 hybrid: the raw aweme detail. play_addr is already the
            # watermark-free stream; download_addr carries the watermark, so it
            # is the last resort rather than an equal alternative.
            or _first_url(video.get("play_addr"))
            or _first_url(
                (video.get("bit_rate") or [{}])[0].get("play_addr")
                if isinstance(video.get("bit_rate"), list) and video.get("bit_rate")
                else None
            )
            or _first_url(video.get("download_addr"))
            # Flat shapes used by some compatible endpoints.
            or data.get("url")
            or data.get("video_url")
            or ""
        )
        if not isinstance(video_url, str) or not video_url.strip():
            raise RuntimeError("Parser response contains no video URL")
        video_url = _validate_media_url(video_url.strip())

        author_raw = data.get("author", {})
        author = (
            author_raw.get("nickname", "")
            if isinstance(author_raw, dict)
            else str(author_raw or "")
        )

        cover = data.get("cover")
        if not isinstance(cover, str):
            cover = _first_url(video.get("cover")) or _first_url(video.get("origin_cover"))

        # v4 reports milliseconds inside `video`, v3 reports seconds at the top
        # level. Telling them apart by magnitude is the only signal available:
        # nothing on these platforms runs for 600 seconds, and nothing runs for
        # 600 milliseconds either, so the boundary is never ambiguous in practice.
        duration = data.get("duration") or video.get("duration") or 0
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 600:
            duration /= 1000

        return ParserResult(
            video_url=video_url,
            title=data.get("title") or data.get("desc") or "",
            author=author,
            cover_url=cover or "",
            duration=duration,
            width=video.get("width") or 0,
            height=video.get("height") or 0,
            extra=data,
        )


# ---------------------------------------------------------------------------
# TikHub.io
# ---------------------------------------------------------------------------

class TikHubParser(BaseParser):
    """Uses TikHub.io's paid API ($0.001/request)."""

    name = "tikhub"
    API_BASE = "https://api.tikhub.io"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers["Authorization"] = f"Bearer {self.api_key}"
        return self._session

    def can_handle(self, url: str) -> bool:
        return True

    def parse(self, url: str, proxy: Optional[str] = None) -> ParserResult:
        proxies = {"http": proxy, "https": proxy} if proxy else None

        # TikHub uses different endpoints for Douyin vs TikTok.
        is_dy = _looks_like_douyin(url)
        if is_dy:
            endpoint = f"{self.API_BASE}/api/v1/douyin/app/v3/fetch_one_video_by_share_url"
        else:
            endpoint = f"{self.API_BASE}/api/v1/tiktok/app/v3/fetch_one_video_by_share_url"

        session = self._get_session()
        resp = session.get(
            endpoint,
            params={"share_url": url},
            timeout=self.timeout,
            proxies=proxies,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("code") != 200 and body.get("code") != 0:
            msg = body.get("message") or body.get("msg") or str(body)
            raise RuntimeError(f"TikHub error: {msg}")

        return self._to_result(body, is_douyin=is_dy)

    # ------------------------------------------------------------------

    @staticmethod
    def _to_result(body: dict, is_douyin: bool) -> ParserResult:
        data = body.get("data", body)
        if not isinstance(data, dict):
            raise RuntimeError("TikHub response is not a JSON object")

        # Navigate into the nested structure.
        # Douyin: data.aweme_detail | data.aweme_details[0]
        # TikTok: data.aweme_detail | data.itemStruct
        details = data.get("aweme_details")
        detail = (
            data.get("aweme_detail")
            or (details[0] if isinstance(details, list) and details else None)
            or data.get("itemStruct")
            or data
        )
        if not isinstance(detail, dict):
            raise RuntimeError("TikHub response has no video detail")

        video = detail.get("video") if isinstance(detail.get("video"), dict) else {}
        video_url = (
            _first_url(video.get("play_addr"))
            or _first_url(video.get("download_addr"))
        )

        if not video_url:
            raise RuntimeError("TikHub response contains no video URL")
        video_url = _validate_media_url(video_url)

        author_info = detail.get("author") if isinstance(detail.get("author"), dict) else {}
        try:
            duration = float(video.get("duration") or 0) / 1000  # ms → s
        except (TypeError, ValueError):
            duration = 0.0

        return ParserResult(
            video_url=video_url,
            title=detail.get("desc") or "",
            author=author_info.get("nickname") or "",
            cover_url=_first_url(video.get("cover")),
            duration=duration,
            width=video.get("width") or 0,
            height=video.get("height") or 0,
            extra=detail,
        )


# ---------------------------------------------------------------------------
# yt-dlp metadata probe  (thin wrapper, always available)
# ---------------------------------------------------------------------------

class YtDlpParser(BaseParser):
    """Extract metadata through yt-dlp's own -J probe.

    Its place in the chain is mostly a label. The download path excludes it —
    a caller that will run a full yt-dlp download when the chain comes up empty
    gains nothing from a `-J` whose answer it then discards — so this exists to
    keep the chain non-empty, to give `/api/health` something honest to print
    when no third-party parser is configured, and to be available to an operator
    who names `ytdlp` in PARSER_PRIORITY to see what yt-dlp makes of a URL.
    """

    name = "ytdlp"

    def __init__(self, timeout: int = 180):
        self.timeout = timeout

    def can_handle(self, url: str) -> bool:
        return True

    def parse(
        self,
        url: str,
        proxy: Optional[str] = None,
        *,
        extra_args: Optional[List[str]] = None,
    ) -> ParserResult:
        cmd = [
            "yt-dlp", "-J", "--no-playlist", "--no-warnings",
            *(extra_args or []),
            url,
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("yt-dlp metadata probe timed out")

        if proc.returncode != 0 or not (proc.stdout or "").strip():
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
            raise RuntimeError(tail or "yt-dlp returned no metadata")

        data = json.loads(proc.stdout)
        if data.get("_type") == "playlist":
            entries = [e for e in (data.get("entries") or []) if e]
            if not entries:
                raise RuntimeError("yt-dlp: no entries in playlist")
            data = entries[0]

        video_url = data.get("url") or ""
        # yt-dlp's -J sometimes gives a direct URL, sometimes a manifest. For
        # the purpose of the parser chain, any non-empty url counts as success
        # and the actual download will still go through yt-dlp's normal path.
        if not video_url:
            # Fall back to the best format's URL.
            fmts = data.get("formats") or []
            if fmts:
                video_url = fmts[-1].get("url", "")

        if not video_url:
            raise RuntimeError("yt-dlp metadata contains no playable URL")

        return ParserResult(
            video_url=video_url,
            title=data.get("title", ""),
            author=data.get("uploader") or data.get("channel", ""),
            duration=float(data.get("duration") or 0),
            width=data.get("width", 0),
            height=data.get("height", 0),
            extra=data,
        )


# ---------------------------------------------------------------------------
# Chain builder
# ---------------------------------------------------------------------------

# Defaults, read once at import time.
_PARSER_URL = (os.getenv("DOUYIN_PARSER_URL") or "").strip()
_TIKHUB_KEY = (os.getenv("TIKHUB_API_KEY") or "").strip()
_PRIORITY = (os.getenv("PARSER_PRIORITY") or "").strip()
_TIMEOUT = int(os.getenv("PARSER_TIMEOUT") or "15")


# app.platform is the single matcher for both this module and the downloader,
# and it matches on the scheme-and-authority prefix rather than a substring —
# a substring test would accept https://evil.example/?next=douyin.com and hand
# an arbitrary host to the parsers. app.platform imports nothing from app, so
# the dependency only points one way.


def _looks_like_douyin(url: str) -> bool:
    return is_douyin(url or "")


def _looks_like_tiktok_or_douyin(url: str) -> bool:
    url = url or ""
    return is_douyin(url) or is_tiktok(url)


def build_parser_chain(
    parser_url: str = _PARSER_URL,
    tikhub_key: str = _TIKHUB_KEY,
    priority: str = _PRIORITY,
    timeout: int = _TIMEOUT,
) -> List[BaseParser]:
    """Assemble the parser chain from environment configuration.

    Returns a list of parsers in priority order. An explicit PARSER_PRIORITY is
    honoured exactly, including the decision to leave `ytdlp` out — that costs
    nothing, because a caller whose chain comes up empty falls back to a full
    yt-dlp download anyway, and listing it here only buys a second `-J` probe
    whose answer is thrown away. Omitting PARSER_PRIORITY keeps yt-dlp last.
    """
    available: dict[str, BaseParser] = {}
    if parser_url:
        available["self_hosted"] = SelfHostedParser(parser_url, timeout)
    if tikhub_key:
        available["tikhub"] = TikHubParser(tikhub_key, timeout)
    # yt-dlp is always *available*; whether it is used depends on the order.
    available["ytdlp"] = YtDlpParser(timeout=180)

    if priority:
        order = [s.strip().lower() for s in priority.split(",") if s.strip()]
    else:
        order = ["self_hosted", "tikhub", "ytdlp"]

    chain: List[BaseParser] = []
    for name in order:
        if name in available and available[name] not in chain:
            chain.append(available[name])

    # A priority list that names nothing installed would leave no parser at all,
    # and an empty chain is indistinguishable from "everything failed" at the
    # call site. yt-dlp backfills that case only.
    if not chain:
        chain.append(available["ytdlp"])

    return chain


# Module-level chain, built once at import.
_chain: Optional[List[BaseParser]] = None


def _get_chain() -> List[BaseParser]:
    global _chain
    if _chain is None:
        _chain = build_parser_chain()
    return _chain


def parser_chain_info() -> List[dict]:
    """Summarise the configured chain for /api/health and /api/info."""
    return [
        {"name": p.name, "type": type(p).__name__}
        for p in _get_chain()
    ]


def has_external_parser() -> bool:
    """Whether at least one non-yt-dlp parser is configured."""
    return any(p.name != "ytdlp" for p in _get_chain())


def resolve_video(
    url: str,
    proxy: Optional[str] = None,
    *,
    exclude: Optional[Iterable[str]] = None,
) -> tuple[ParserResult, str]:
    """Walk the parser chain and return the first successful result.

    Returns (result, parser_name). Raises RuntimeError when every parser fails.

    *exclude* drops parsers by name. It exists for the caller that already
    intends to run a full yt-dlp download when the chain comes up empty: asking
    YtDlpParser for metadata first would spend a second `-J` — through a metered
    proxy, on a site that is rate limiting us — on an answer that gets discarded.
    """
    if not _looks_like_tiktok_or_douyin(url):
        raise ValueError(f"URL is not a Douyin/TikTok link: {url}")

    skip = {name.strip().lower() for name in (exclude or ())}
    chain = [p for p in _get_chain() if p.name not in skip]
    if not chain:
        raise RuntimeError("没有可用的解析器")

    errors: list[tuple[str, str]] = []

    for parser in chain:
        if not parser.can_handle(url):
            continue
        try:
            result = parser.parse(url, proxy)
            print(
                f"[parser] {parser.name} 解析成功: {url}",
                flush=True,
            )
            return result, parser.name
        except Exception as exc:
            reason = str(exc)[:200]
            print(
                f"[parser] {parser.name} 解析失败: {reason}",
                flush=True,
            )
            errors.append((parser.name, reason))

    detail = "; ".join(f"{n}: {r}" for n, r in errors)
    raise RuntimeError(f"所有解析器均失败 — {detail}")
