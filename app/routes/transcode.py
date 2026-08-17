"""Transcode endpoint: on-demand re-encode to H.264/AAC."""

from fastapi import APIRouter, HTTPException

from app.downloader import do_transcode
from app.jobs import jobs, jobs_lock, transcode_executor
from app.routes._helpers import job_file_path

router = APIRouter()


@router.post("/api/jobs/{job_id}/transcode")
async def transcode_job_file(job_id: str, payload: dict):
    """Re-encode one video to H.264/AAC. Explicit action: it is CPU expensive."""
    rel = payload.get("path")

    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")

        videos = {f["path"] for f in job.get("files", []) if f.get("kind") == "video"}
        if not isinstance(rel, str) or rel not in videos:
            raise HTTPException(status_code=400, detail="无效的视频文件")

        transcodes = job.setdefault("transcodes", {})
        if transcodes.get(rel, {}).get("status") == "running":
            return {"ok": True, "status": "running"}
        transcodes[rel] = {"status": "running"}

    job_file_path(job_id, rel)
    transcode_executor.submit(do_transcode, job_id, rel)
    return {"ok": True, "status": "running"}
