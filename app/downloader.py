"""Core download logic: subprocess execution and multi-engine orchestration."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import parsers
from app.config import (
    BROWSER_UA,
    DOWNLOAD_ROOT,
    MIN_MEDIA_BYTES,
    QUALITY_AUDIO,
    QUALITY_COMPAT,
)
from app.cookies import cookie_args_for
from app.jobs import jobs, jobs_lock
from app.media import (
    build_file_item,
    clear_partials,
    collect_files,
    transcode_to_h264,
)
from app.platform import (
    is_bilibili,
    is_douyin,
    is_instagram,
    is_tiktok,
    platform_name_for,
)
from app.proxy import proxy_args_for, proxy_configured_for, proxy_url_from_args
from app.quality import (
    parse_quality,
    yt_dlp_download_args,
    yt_dlp_impersonate_args,
)


# ── Tool output classification ──────────────────────────────────────────────

def _looks_rate_limited(low: str) -> bool:
    """Whether a line of tool output says "this address is asking too often".

    429 is the obvious one. **412 Precondition Failed is Bilibili's**: its API
    answers 412 once an address has made a handful of requests in quick
    succession, then goes back to answering normally a few minutes later.
    Nothing about the request is wrong — the same bare `yt-dlp -J` that gets a
    412 succeeds unchanged after a pause, and no combination of Referer,
    User-Agent, impersonation or anonymous cookies avoids it.
    """
    return (
        "429" in low
        or "too many requests" in low
        or "412" in low
        or "precondition failed" in low
    )


def _looks_auth_required(low: str) -> bool:
    """Whether a line of tool output says "this needs a cookie jar"."""
    return (
        "login required" in low
        or "authentication required" in low
        # Douyin/TikTok phrase it as needing fresh cookies even though no
        # account login is involved.
        or "cookies are needed" in low
        or "fresh cookies" in low
        or "sign in to confirm" in low
        # gallery-dl uses none of the wordings above when an Instagram session
        # is missing or stale — it surfaces the transport error instead.
        or "401 unauthorized" in low
        or "403 forbidden" in low
        or "login_required" in low
        or "checkpoint_required" in low
    )


def _get_flags(job_id: str) -> tuple[bool, bool]:
    with jobs_lock:
        job = jobs.get(job_id) or {}
        return bool(job.get("rate_limited")), bool(job.get("auth_required"))


def _clear_flags(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job["rate_limited"] = False
            job["auth_required"] = False


def _update_job(job_id: str, **fields) -> None:
    """Update a job that may have been deleted while the worker was running."""
    with jobs_lock:
        job = jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _set_engine(job_id: str, name: str) -> None:
    _update_job(job_id, engine=name)


def _record_progress(job_id: str, line: str) -> None:
    _update_job(job_id, last_line=line)


# ── Subprocess execution ────────────────────────────────────────────────────

def run_process(cmd: list[str], cwd: Path, job_id: str) -> tuple[int, list[str]]:
    """Run *cmd* as a subprocess, streaming its output into the job log."""
    _update_job(job_id, command=" ".join(cmd[:2]) + " ...")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            lines.append(line)
        # One acquisition per line: yt-dlp repaints its progress line many times
        # a second, and the flags below have to be read off the same line.
        low = line.lower()
        with jobs_lock:
            job = jobs.get(job_id)
            if job is not None:
                job["log"] = lines[-100:]
                job["last_line"] = line
                # Surface rate-limit/auth hints to the UI.
                if _looks_rate_limited(low):
                    job["rate_limited"] = True
                if _looks_auth_required(low):
                    job["auth_required"] = True
    rc = proc.wait()
    return rc, lines


# ── Douyin / TikTok parser chain ────────────────────────────────────────────

def _referer_for(url: str) -> str:
    return "https://www.tiktok.com/" if is_tiktok(url) else "https://www.douyin.com/"


def _http_download(
    url: str, dest: Path, job_id: str, *,
    proxy: Optional[str] = None,
    referer: str = "https://www.douyin.com/",
    chunk_size: int = 1024 * 1024,
) -> None:
    """Stream a file from *url* to *dest*, or leave nothing behind.

    Three things this must not do, each of which ends with the user holding a
    file that is not the video they asked for:

      * finish at the destination path after failing partway — `collect_files`
        would count the fragment and the job would report success. Hence the
        `.part` staging file and the rename that only happens once the body is
        fully read.
      * accept an error page. The CDN says no with HTTP 200 and a few hundred
        bytes of JSON, so the status code is not the check that matters.
      * ignore the proxy. A request that skips it shows the origin's own address
        to a site the operator deliberately routed around.
    """
    import requests as _requests

    proxies = {"http": proxy, "https": proxy} if proxy else None
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)

    try:
        written = 0
        with _requests.get(
            url,
            stream=True,
            # (connect, read): the read timeout is per chunk, not for the whole
            # transfer, so a large file over a slow link is fine and a stalled
            # socket still gives up.
            timeout=(15, 120),
            proxies=proxies,
            headers={"User-Agent": BROWSER_UA, "Referer": referer},
        ) as resp:
            resp.raise_for_status()

            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype.startswith(("text/", "application/json")):
                raise RuntimeError(f"直链返回的不是媒体内容（Content-Type: {ctype}）")

            last_report = 0
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written += len(chunk)
                    # The UI reads progress off the tool's output lines, and
                    # this path has no tool. Without this the job sits on
                    # yt-dlp's last line for the whole transfer and looks hung.
                    if written - last_report >= 4 * chunk_size:
                        last_report = written
                        _record_progress(
                            job_id, f"[direct] 已下载 {written / 1048576:.1f} MiB"
                        )

        if written < MIN_MEDIA_BYTES:
            raise RuntimeError(f"直链只返回了 {written} 字节，不是完整视频")

        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def _download_direct_url(
    job_id: str, result: parsers.ParserResult, job_dir: Path,
    cookie_args, proxy_args, url: str,
) -> tuple[int, list[str]]:
    """Download a video from a direct URL resolved by a parser.

    yt-dlp first — not for its extractor, which is exactly what the parser
    exists to bypass, but for its download engine: resumption, retries and the
    progress lines the UI reads. If it cannot fetch the link, a plain streaming
    HTTP request tries again with browser-shaped headers.

    Quality selection does not apply here. Douyin and TikTok serve a single
    pre-muxed stream and the parser resolved that one stream; there are no
    alternative renditions behind this URL to pick between.
    """
    filename = result.filename

    # `-o` is a *template*, and "%" is its escape character — a title like
    # "100%好看" makes yt-dlp fail on an unknown field rather than write the
    # file. Doubling it produces the literal character back.
    template = filename.replace("%", "%%")

    cmd = [
        "yt-dlp",
        "--no-mtime",
        "-P", str(job_dir),
        "-o", template,
        # No playlist handling or extraction needed for a direct URL.
        "--no-playlist",
        # The CDN checks these the same way the page does, so the direct link
        # 403s without them even though it needs no cookies.
        "--user-agent", BROWSER_UA,
        "--add-header", f"Referer:{_referer_for(url)}",
        *yt_dlp_impersonate_args(url),
        *cookie_args,
        *proxy_args,
        result.video_url,
    ]

    rc, lines = run_process(cmd, job_dir, job_id)

    if collect_files(job_dir):
        return rc, lines

    # If yt-dlp cannot handle the direct URL (some CDN URLs need a browser-like
    # request), fall back to a plain HTTP download. Anything the failed attempt
    # left behind goes first: a leftover fragment would otherwise sit next to
    # the file this writes and end up published alongside it.
    clear_partials(job_dir)
    print("[parser] yt-dlp 直链下载失败，尝试 HTTP 直接下载", flush=True)
    try:
        _http_download(
            result.video_url, job_dir / filename, job_id,
            proxy=proxy_url_from_args(proxy_args),
            referer=_referer_for(url),
        )
        rc = 0
        lines.append("HTTP 直接下载完成")
    except Exception as exc:
        lines.append(f"HTTP 直接下载失败: {exc}")

    return rc, lines


def _parser_then_ytdlp(
    job_id: str, url: str, quality: str, job_dir: Path,
    cookie_args, proxy_args,
) -> tuple[int, list[str]]:
    """Try the parser chain to resolve a direct video URL for Douyin/TikTok.

    If a parser succeeds, download the video directly from the resolved URL.
    Every other outcome — no parser could resolve it, or the resolved link
    turned out to be undownloadable — ends in the ordinary yt-dlp path.

    That second fallback is the one worth spelling out. A Douyin CDN link is
    signed and expires, and a parser can hand back a URL that was valid when it
    was minted and 403s by the time we fetch it. Without the fallback the job
    would fail on a link yt-dlp could have served itself.
    """
    # Audio-only skips the chain entirely, and has to be checked before anything
    # is resolved. The direct link is a muxed video stream; downloading it would
    # hand back an .mp4 to someone who asked for 仅音频, and extracting the audio
    # means running yt-dlp and ffmpeg anyway.
    if parse_quality(quality) == QUALITY_AUDIO:
        return _run_yt_dlp(job_id, url, quality, job_dir, cookie_args, proxy_args)

    parser_proxy = proxy_url_from_args(proxy_args)
    try:
        # The chain's own yt-dlp parser is skipped: this caller runs a full
        # yt-dlp download when the chain comes up empty, so asking yt-dlp for
        # metadata here would spend an extra `-J` on an answer that is then
        # thrown away.
        result, parser_name = parsers.resolve_video(
            url, proxy=parser_proxy, exclude={"ytdlp"},
        )
    except Exception as exc:
        print(f"[parser] 所有解析器失败，回退完整 yt-dlp: {exc}", flush=True)
        return _run_yt_dlp(job_id, url, quality, job_dir, cookie_args, proxy_args)

    _set_engine(job_id, f"parser:{parser_name}")
    rc, lines = _download_direct_url(
        job_id, result, job_dir, cookie_args, proxy_args, url,
    )
    if collect_files(job_dir):
        return rc, lines

    print("[parser] 直链下载没拿到文件，回退完整 yt-dlp", flush=True)
    clear_partials(job_dir)
    # The parser path failing does not tell us anything about the site's view of
    # this address, and a stale flag here would suppress the yt-dlp attempt's
    # own verdict in the error message.
    _clear_flags(job_id)
    _set_engine(job_id, "yt-dlp (fallback)")
    rc2, lines2 = _run_yt_dlp(
        job_id, url, quality, job_dir, cookie_args, proxy_args
    )
    return rc2, lines + lines2


# ── yt-dlp / gallery-dl orchestration ───────────────────────────────────────

def _run_yt_dlp(
    job_id: str, url: str, quality: str, job_dir: Path, cookie_args, proxy_args,
) -> tuple[int, list[str]]:
    cmd = [
        "yt-dlp", *yt_dlp_download_args(url, quality, job_dir),
        *cookie_args, *proxy_args, url,
    ]
    return run_process(cmd, job_dir, job_id)


def _run_gallery_dl(
    job_id: str, url: str, job_dir: Path, cookie_args, proxy_args,
) -> tuple[int, list[str]]:
    cmd = [
        "gallery-dl",
        "--no-mtime",
        "-D", str(job_dir),
        *cookie_args,
        *proxy_args,
        url,
    ]
    return run_process(cmd, job_dir, job_id)


def _attempt_download(
    job_id: str, url: str, engine: str, quality: str, job_dir: Path,
    cookie_args, proxy_args,
) -> tuple[int, list[str]]:
    """Run the download once, picking the engine chain for the platform."""
    # Instagram:
    # - Reels/TV: yt-dlp first, then gallery-dl fallback.
    # - /p/: gallery-dl only (photos/carousels) — image items have no video
    #   formats, so a yt-dlp fallback cannot help.
    # Cookies are optional: only passed when a cookies.txt exists.
    if is_instagram(url):
        path = url.lower().split("?", 1)[0]
        reel_like = any(x in path for x in ("/reel/", "/reels/", "/tv/"))

        first_engine = "yt-dlp" if reel_like else "gallery-dl"
        second_engine = "gallery-dl" if reel_like else None

        def run_engine(name):
            _set_engine(job_id, name)
            if name == "gallery-dl":
                return _run_gallery_dl(job_id, url, job_dir, cookie_args, proxy_args)
            return _run_yt_dlp(
                job_id, url, quality, job_dir, cookie_args, proxy_args
            )

        rc, lines = run_engine(first_engine)

        rate_limited, auth_required = _get_flags(job_id)

        # Neither a rate limit nor an authentication failure is the tool's
        # fault, so retrying with the other one cannot help — it just costs a
        # second request against a site that is already refusing us.
        if ((not collect_files(job_dir)) and not rate_limited
                and not auth_required and second_engine):
            # Remove partial files before the fallback so the second extractor
            # gets a clean directory.
            clear_partials(job_dir)
            rc, lines = run_engine(second_engine)

        return rc, lines

    if engine == "gallery-dl":
        _set_engine(job_id, "gallery-dl")
        rc, lines = _run_gallery_dl(job_id, url, job_dir, cookie_args, proxy_args)

        rate_limited, _ = _get_flags(job_id)

        if (not collect_files(job_dir)) and not rate_limited:
            clear_partials(job_dir)
            _set_engine(job_id, "yt-dlp (fallback)")
            rc, lines = _run_yt_dlp(
                job_id, url, quality, job_dir, cookie_args, proxy_args
            )

        return rc, lines

    # Douyin / TikTok: try the parser chain before yt-dlp. yt-dlp's Douyin
    # extractor breaks whenever the platform rotates its X-Bogus / A_Bogus
    # signatures, which is often; a configured parser sidesteps extraction
    # entirely by handing back the direct CDN URL.
    if (is_douyin(url) or is_tiktok(url)) and parsers.has_external_parser():
        return _parser_then_ytdlp(
            job_id, url, quality, job_dir, cookie_args, proxy_args,
        )

    return _run_yt_dlp(job_id, url, quality, job_dir, cookie_args, proxy_args)


# ── Failure reporting ───────────────────────────────────────────────────────

def _failure_message(url: str, job_id: str, lines: list[str]) -> str:
    """Why the download failed, in terms the operator can act on.

    Cookies are server-side configuration in Lite, so a cookie demand is a note
    to whoever runs the deployment — pointing the visitor at an upload button
    that no longer exists would be worse than saying nothing.
    """
    rate_limited, auth_required = _get_flags(job_id)
    platform = platform_name_for(url)

    if auth_required:
        head = (
            f"{platform} 要求提供有效的 Cookies（不一定需要登录账号）。"
            f"Cookies 由服务端配置：把导出的 cookies.txt 放进 COOKIES_DIR，"
            f"或用 <平台>_COOKIES 环境变量提供，然后重启服务。"
        )
        # For Douyin and TikTok the cookie demand is what the *fallback* path
        # says, not the primary one. Sending someone off to export cookies while
        # their parser sits unconfigured points them at the wrong problem.
        if is_douyin(url) or is_tiktok(url):
            if not parsers.has_external_parser():
                head += (
                    "\n\n不过更可能的问题是：没有配置解析器。配好之后多数公开视频"
                    "根本不需要 Cookies —— 在 .env 里设 DOUYIN_PARSER_URL"
                    "（用自带容器还要写 COMPOSE_PROFILES=douyin-parser）。"
                )
            else:
                head += (
                    "\n\n解析器是配了的，但这次没解析成功才回退到需要 Cookies 的方式。"
                    "先查解析器：docker compose logs --tail=50 downloader | grep '\\[parser\\]'"
                )
    elif rate_limited and is_bilibili(url):
        # Naming the platform's own behaviour is the difference between a user
        # retrying in two minutes and an operator re-exporting cookies for an hour.
        head = ("哔哩哔哩返回 412：这是它的限流，不是链接或 Cookies 的问题。"
                "同一个出口连续请求几次就会触发，隔几分钟自动恢复。"
                "配置 BILIBILI_PROXY 换个出口也能缓解。")
    elif rate_limited:
        head = "目标站点返回 429 / 412：当前出口 IP 被限流，请稍后再试或更换代理出口。"
    else:
        head = "下载失败，请检查链接、代理、Cookies 或目标站点限制。"

    tail = "\n".join((lines or [])[-12:])
    return head + (f"\n\n{tail}" if tail else "")


# ── Job entry points ────────────────────────────────────────────────────────

def do_download(job_id: str, url: str, engine: str, quality: str = QUALITY_COMPAT):
    """Execute the full download workflow for a single job."""
    job_dir = DOWNLOAD_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    _update_job(
        job_id,
        status="downloading",
        engine=engine,
        proxy_used=proxy_configured_for(url),
    )

    cookie_args = cookie_args_for(url)
    proxy_args = proxy_args_for(url)

    try:
        _rc, lines = _attempt_download(
            job_id, url, engine, quality, job_dir, cookie_args, proxy_args,
        )

        files = collect_files(job_dir)

        # Some extractors return a non-zero code after successfully saving
        # some/all media items. The actual presence of media files is the
        # authoritative success signal for this UI.
        if not files:
            raise RuntimeError(_failure_message(url, job_id, lines))

        # Do not automatically ZIP multi-file posts. Keep the individual files
        # so the WebUI can preview and select them.
        file_items = [
            item for item in (build_file_item(p, job_dir) for p in sorted(files))
            if item
        ]
        if not file_items:
            raise RuntimeError("下载完成但没有可用文件")

        # For a single file, keep the direct download convenience.
        result = job_dir / file_items[0]["path"] if len(file_items) == 1 else None

        _update_job(
            job_id,
            status="done",
            result=str(result) if result else None,
            filename=result.name if result else None,
            size=result.stat().st_size if result else None,
            files=file_items,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        _update_job(
            job_id,
            status="error",
            error=str(e),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


def do_transcode(job_id: str, rel_path: str):
    """Re-encode one video to H.264/AAC, updating the job state."""
    job_dir = (DOWNLOAD_ROOT / job_id).resolve()
    try:
        converted = transcode_to_h264(job_dir / rel_path)
        # transcode_to_h264 already writes with +faststart, so skip the remux.
        item = build_file_item(converted, job_dir, remux=False)
        if not item:
            raise RuntimeError("转码结果不在任务目录内")

        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return
            job["files"] = [
                item if f.get("path") == rel_path else f
                for f in job.get("files", [])
            ]
            job.setdefault("transcodes", {})[rel_path] = {
                "status": "done",
                "path": item["path"],
            }
            if len(job["files"]) == 1:
                job.update(
                    result=str(converted),
                    filename=converted.name,
                    size=item["size"],
                )
    except Exception as exc:
        with jobs_lock:
            job = jobs.get(job_id)
            if job:
                job.setdefault("transcodes", {})[rel_path] = {
                    "status": "error",
                    "error": str(exc),
                }
