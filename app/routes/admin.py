"""Admin console: page, runtime overview, job management, platform cookies.

Everything here sits behind `require_admin`. The public download page has no
cookie settings and no job listing for other people's downloads — that split is
the point of the console, not an accident of layout.
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app import parsers
from app.auth import (
    ADMIN_TOKEN_HEADER,
    admin_enabled,
    require_admin,
    token_is_weak,
)
from app.cleanup import cleanup_downloads_once, cleanup_old
from app.config import (
    COOKIE_ENV_VARS,
    COOKIE_FILE,
    COOKIE_FILES,
    COOKIES_DIR,
    DOWNLOAD_ROOT,
    MAX_WORKERS,
    RETENTION_HOURS,
    TEMPLATES_DIR,
)
from app.cookies import cookie_status
from app.jobs import jobs, jobs_lock
from app.proxy import PLATFORM_PROXIES, proxy_coverage

router = APIRouter()
admin_only = [Depends(require_admin)]

MAX_COOKIE_BYTES = 10 * 1024 * 1024


# ── Page ────────────────────────────────────────────────────────────────────

@router.get("/admin", include_in_schema=False)
def admin_page():
    """Serve the console shell.

    Not under /static on purpose: with no token configured this 404s, and the
    page cannot be reached at all rather than rendering a console that nothing
    behind it will answer.
    """
    if not admin_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(TEMPLATES_DIR / "admin.html")


@router.get("/api/admin/ping", dependencies=admin_only)
def ping():
    """Cheapest possible token check, for the login gate."""
    return {"ok": True}


# ── Overview ────────────────────────────────────────────────────────────────

def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


@router.get("/api/admin/overview", dependencies=admin_only)
def overview():
    with jobs_lock:
        snapshot = [dict(job) for job in jobs.values()]

    counts: dict[str, int] = {}
    for job in snapshot:
        status = job.get("status") or "unknown"
        counts[status] = counts.get(status, 0) + 1

    try:
        job_dirs = [p for p in DOWNLOAD_ROOT.iterdir() if p.is_dir()]
    except OSError:
        job_dirs = []

    usage = shutil.disk_usage(DOWNLOAD_ROOT) if DOWNLOAD_ROOT.exists() else None

    return {
        "tools": {
            "yt_dlp": shutil.which("yt-dlp") is not None,
            "gallery_dl": shutil.which("gallery-dl") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
        },
        "jobs": {
            "total": len(snapshot),
            "by_status": counts,
            "queued": counts.get("queued", 0),
            "running": counts.get("downloading", 0),
        },
        "storage": {
            "download_root": str(DOWNLOAD_ROOT),
            "job_dirs": len(job_dirs),
            "bytes_used": _dir_size(DOWNLOAD_ROOT),
            "disk_free": usage.free if usage else None,
            "disk_total": usage.total if usage else None,
        },
        "capacity": {"workers": MAX_WORKERS, "retention_hours": RETENTION_HOURS},
        "parser_chain": parsers.parser_chain_info(),
        "has_external_parser": parsers.has_external_parser(),
        "proxies": proxy_coverage(),
        "cookies": cookie_status(),
        "warnings": _warnings(),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


def _warnings() -> list[dict]:
    """Configuration problems worth saying out loud on every page load."""
    out = []
    if token_is_weak():
        out.append({
            "level": "warn",
            "text": "ADMIN_TOKEN 太短，建议至少 16 位随机字符："
                    "openssl rand -base64 24",
        })
    if not parsers.has_external_parser():
        out.append({
            "level": "info",
            "text": "未配置抖音/TikTok 解析器。抖音的 extractor 经常因平台反爬更新"
                    "而失效，配置 DOUYIN_PARSER_URL 后大多数公开视频不再需要 Cookies。",
        })
    return out


# ── Jobs ────────────────────────────────────────────────────────────────────

@router.get("/api/admin/jobs", dependencies=admin_only)
def list_jobs(status: str = "", limit: int = 200):
    with jobs_lock:
        snapshot = [dict(job) for job in jobs.values()]

    if status:
        snapshot = [j for j in snapshot if j.get("status") == status]

    # Newest first: the job someone is asking about is the one that just ran.
    snapshot.sort(key=lambda j: j.get("created_at") or "", reverse=True)

    rows = []
    for job in snapshot[: max(1, min(limit, 1000))]:
        files = job.get("files") or []
        rows.append({
            "id": job.get("id"),
            "url": job.get("url"),
            "status": job.get("status"),
            "engine": job.get("engine"),
            "quality": job.get("quality"),
            "created_at": job.get("created_at"),
            "finished_at": job.get("finished_at"),
            "file_count": len(files),
            "size": sum(f.get("size") or 0 for f in files) or job.get("size"),
            "proxy_used": job.get("proxy_used", False),
            "rate_limited": job.get("rate_limited", False),
            "auth_required": job.get("auth_required", False),
            # The whole log would be a megabyte of repainted progress lines.
            "last_line": job.get("last_line"),
            "error": (job.get("error") or "")[:500] or None,
        })

    return {"jobs": rows, "total": len(snapshot)}


@router.get("/api/admin/jobs/{job_id}/log", dependencies=admin_only)
def job_log(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"id": job_id, "command": job.get("command"), "log": job.get("log", [])}


@router.delete("/api/admin/jobs/{job_id}", dependencies=admin_only)
def delete_job(job_id: str):
    with jobs_lock:
        job = jobs.pop(job_id, None)

    # The directory is removed either way. A job the store has already forgotten
    # can still have files on disk — that is exactly the state a cleanup gap
    # leaves behind, and refusing to delete it would make the console useless
    # for the one case it is needed for.
    target = (DOWNLOAD_ROOT / job_id).resolve()
    if DOWNLOAD_ROOT.resolve() not in target.parents:
        raise HTTPException(status_code=400, detail="非法任务 ID")
    existed = target.exists()
    shutil.rmtree(target, ignore_errors=True)

    if not job and not existed:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "id": job_id}


@router.post("/api/admin/maintenance/cleanup", dependencies=admin_only)
async def run_cleanup(scope: str = "expired"):
    """Run a cleanup pass now instead of waiting for the schedule.

    `expired` applies the retention window; `all` is the nightly sweep, which
    removes every directory that is not backing a running job.
    """
    before = len(list(DOWNLOAD_ROOT.iterdir())) if DOWNLOAD_ROOT.exists() else 0
    if scope == "all":
        await cleanup_downloads_once()
    else:
        cleanup_old()
    after = len(list(DOWNLOAD_ROOT.iterdir())) if DOWNLOAD_ROOT.exists() else 0
    return {"ok": True, "scope": scope, "removed": max(0, before - after)}


# ── Cookies ─────────────────────────────────────────────────────────────────

def _cookie_target(platform: str) -> Path:
    target = COOKIE_FILES.get((platform or "").strip().lower())
    if target is None:
        raise HTTPException(status_code=400, detail="不支持的平台")
    return target


def _looks_like_jar(content: bytes) -> bool:
    """Whether an upload is actually a Netscape cookie jar.

    Checked because the failure mode otherwise is silent: a JSON export or an
    empty file uploads fine, reports success, and then every download keeps
    failing with the same auth error the operator just tried to fix.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "\t" in text or "# Netscape" in text or "# HTTP Cookie File" in text


def _cookie_rows() -> list[dict]:
    status = cookie_status()
    rows = []
    for name, path in COOKIE_FILES.items():
        env_var = COOKIE_ENV_VARS[name]
        from_env = bool((os.getenv(env_var) or "").strip())
        try:
            stat = path.stat() if path.is_file() else None
        except OSError:
            stat = None
        rows.append({
            "platform": name,
            "configured": status.get(name, False),
            "path": str(path),
            "size": stat.st_size if stat else None,
            "updated_at": (
                datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                if stat else None
            ),
            # An upload lands on disk, but the environment is re-applied at every
            # startup — so on a platform configured that way, the upload silently
            # reverts on the next `docker compose up`. Saying so is the only way
            # the operator finds out before it bites.
            "env_var": env_var,
            "from_env": from_env,
            "legacy_fallback": (
                name == "instagram"
                and not path.is_file()
                and COOKIE_FILE.is_file()
            ),
        })
    return rows


@router.get("/api/admin/cookies", dependencies=admin_only)
def list_cookies():
    return {"cookies": _cookie_rows(), "cookies_dir": str(COOKIES_DIR)}


@router.post("/api/admin/cookies/{platform}", dependencies=admin_only)
async def upload_cookies(platform: str, file: UploadFile = File(...)):
    target = _cookie_target(platform)

    content = await file.read()
    if len(content) > MAX_COOKIE_BYTES:
        raise HTTPException(status_code=400, detail="Cookies 文件过大")
    if not content.strip():
        raise HTTPException(status_code=400, detail="Cookies 文件为空")
    if not _looks_like_jar(content):
        raise HTTPException(
            status_code=400,
            detail="这不像 Netscape 格式的 cookies.txt（没有制表符分隔的字段）。"
                   "请用浏览器扩展导出 cookies.txt，而不是 JSON。",
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        os.chmod(target, 0o600)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入失败: {exc}")

    return {
        "ok": True,
        "platform": platform.lower(),
        "size": len(content),
        "cookies": _cookie_rows(),
    }


@router.delete("/api/admin/cookies/{platform}", dependencies=admin_only)
def delete_cookies(platform: str):
    target = _cookie_target(platform)
    target.unlink(missing_ok=True)
    return {"ok": True, "platform": platform.lower(), "cookies": _cookie_rows()}


# ── Proxies (read-only) ─────────────────────────────────────────────────────

def _mask_proxy(url: str) -> str:
    """Show the shape of a proxy URL without its credentials.

    The console is authenticated, but a proxy password is a credential for
    somebody else's service and there is no reason it needs to be recoverable
    from a browser tab, a screenshot, or a support screen-share.
    """
    if not url:
        return ""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _creds, _, host = rest.rpartition("@")
    return f"{scheme}://***:***@{host}" if scheme else f"***@{host}"


@router.get("/api/admin/proxies", dependencies=admin_only)
def list_proxies():
    return {
        "proxies": [
            {
                "platform": name,
                "configured": bool(value),
                "value": _mask_proxy(value),
                "env_var": f"{'TWITTER' if name == 'twitter' else name.upper()}_PROXY",
            }
            for name, value in PLATFORM_PROXIES.items()
        ],
        # Proxies are process-level configuration; changing them means editing
        # .env and restarting. Said here so the console does not look broken for
        # lacking an edit button.
        "editable": False,
    }


# ── Token surface for the login gate ────────────────────────────────────────

@router.get("/api/admin/config", include_in_schema=False)
def admin_config(request: Request):
    """Whether a console exists here. Deliberately unauthenticated and empty.

    Only reachable when a token is configured, and it returns nothing an
    unauthenticated caller could not learn by requesting /admin.
    """
    if not admin_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return JSONResponse({"admin_enabled": True, "token_header": ADMIN_TOKEN_HEADER})
