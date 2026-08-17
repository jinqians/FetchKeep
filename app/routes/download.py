"""Job lifecycle and file download endpoints."""

import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.config import ARCHIVE_DIRNAME, DOWNLOAD_ROOT, MEDIA_TYPES, QUALITY_COMPAT
from app.downloader import do_download
from app.jobs import executor, jobs, jobs_lock
from app.platform import detect_engine
from app.quality import parse_quality
from app.routes._helpers import job_file_path, validate_url

router = APIRouter()


@router.post("/api/jobs")
async def create_job(
    url: str = Form(...),
    engine: str = Form("auto"),
    quality: str = Form(QUALITY_COMPAT),
):
    url = validate_url(url)

    if engine == "auto":
        engine = detect_engine(url)

    if engine not in ("gallery-dl", "yt-dlp"):
        raise HTTPException(status_code=400, detail="无效的下载引擎")

    quality = parse_quality(quality)
    job_id = os.urandom(6).hex()

    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "url": url,
            "engine": engine,
            "quality": quality,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "log": [],
            "last_line": "",
            "proxy_used": False,
            "rate_limited": False,
            "auth_required": False,
            "transcodes": {},
        }

    executor.submit(do_download, job_id, url, engine, quality)
    return {"id": job_id}


@router.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return JSONResponse(job)


@router.get("/api/jobs/{job_id}/download")
def download_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="文件尚未准备好")

    # A multi-file job finishes with no single `result`: the WebUI is expected
    # to pick files and use /download-selected. Without this the Path() below
    # raises TypeError and the caller sees a 500 instead of the reason.
    if not job.get("result"):
        raise HTTPException(
            status_code=400,
            detail="该任务包含多个文件，请选择要下载的文件",
        )

    path = Path(job["result"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已经被清理")

    return FileResponse(
        path,
        filename=job.get("filename", path.name),
        media_type="application/octet-stream",
    )


@router.get("/api/jobs/{job_id}/files")
def list_job_files(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "id": job_id,
        "files": job.get("files", []),
    }


@router.get("/api/jobs/{job_id}/files/{file_path:path}")
def get_job_file(job_id: str, file_path: str, download: int = 0):
    path = job_file_path(job_id, file_path)

    # Let Starlette build the Content-Disposition header. A hand-written
    # f'inline; filename="{name}"' cannot be latin-1 encoded and makes the
    # whole response fail with 500 whenever the filename contains non-ASCII
    # characters (e.g. a CJK YouTube/TikTok title).
    if download:
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/octet-stream",
            content_disposition_type="attachment",
        )

    return FileResponse(
        path,
        filename=path.name,
        media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        content_disposition_type="inline",
    )


@router.post("/api/jobs/{job_id}/download-selected")
async def download_selected(job_id: str, payload: dict):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    selected = payload.get("files")
    if not isinstance(selected, list) or not selected:
        raise HTTPException(status_code=400, detail="请选择至少一个文件")

    job_dir = (DOWNLOAD_ROOT / job_id).resolve()
    paths = []
    allowed = {item["path"] for item in job.get("files", [])}

    for rel in selected:
        if not isinstance(rel, str) or rel not in allowed:
            raise HTTPException(status_code=400, detail="包含无效文件")
        p = job_file_path(job_id, rel)
        paths.append(p)

    if len(paths) == 1:
        return FileResponse(
            paths[0],
            filename=paths[0].name,
            media_type="application/octet-stream",
        )

    # Into the archive directory rather than next to the media: collect_files
    # excludes it, so the ZIP does not come back as a file of the job the next
    # time the directory is listed.
    archive_dir = job_dir / ARCHIVE_DIRNAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    zip_path = archive_dir / "selected-download.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, p.relative_to(job_dir))

    return FileResponse(
        zip_path,
        filename="selected-download.zip",
        media_type="application/zip",
    )


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    with jobs_lock:
        job = jobs.pop(job_id, None)

    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    shutil.rmtree(DOWNLOAD_ROOT / job_id, ignore_errors=True)
    return {"ok": True}
