"""Shared route helpers."""

import re
from pathlib import Path

from fastapi import HTTPException

from app.config import DOWNLOAD_ROOT


def validate_url(url: str) -> str:
    """Sanitise and validate a user-supplied URL."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(status_code=400, detail="请输入完整的 http/https URL")
    if len(url) > 4096:
        raise HTTPException(status_code=400, detail="URL 太长")
    return url


def job_file_path(job_id: str, rel_path: str) -> Path:
    """Resolve a relative file path inside a job directory, with safety checks."""
    job_dir = (DOWNLOAD_ROOT / job_id).resolve()
    target = (job_dir / rel_path).resolve()
    if target != job_dir and job_dir not in target.parents:
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target
