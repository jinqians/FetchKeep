"""Scheduled cleanup tasks for old downloads."""

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import DOWNLOAD_ROOT, RETENTION_HOURS
from app.jobs import jobs, jobs_lock

ACTIVE_STATUSES = {"queued", "downloading", "processing"}


def active_job_dirs() -> set[Path]:
    """Resolved directories of jobs that are still running.

    The directory is derived from the job id rather than read off the job: no
    code path ever stored a "dir" key, so looking one up returned None for every
    job and left this set empty — which meant the scheduled cleanup deleted the
    working directory of any download unlucky enough to be running at 00:00 UTC.

    The snapshot is taken under the lock because a worker thread can insert or
    finish a job while this iterates.
    """
    with jobs_lock:
        active_ids = [
            job_id for job_id, job in jobs.items()
            if job.get("status") in ACTIVE_STATUSES
        ]

    dirs = set()
    for job_id in active_ids:
        try:
            dirs.add((DOWNLOAD_ROOT / job_id).resolve())
        except OSError:
            pass
    return dirs


async def cleanup_downloads_once():
    """Remove completed download directories under /data/downloads.

    The active in-memory jobs are protected so a download currently running
    at 00:00 UTC is not deleted. Completed/failed job directories are removed.
    """
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    active_dirs = active_job_dirs()

    removed = 0
    dropped: list[str] = []
    for item in DOWNLOAD_ROOT.iterdir():
        try:
            resolved = item.resolve()
            if resolved in active_dirs:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                dropped.append(item.name)
                removed += 1
            elif item.is_file():
                item.unlink(missing_ok=True)
                removed += 1
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[cleanup] failed to remove {item}: {exc}", flush=True)

    forget_jobs(dropped)

    print(
        f"[cleanup] UTC 00:00 cleanup finished, removed {removed} download items",
        flush=True,
    )


async def downloads_cleanup_loop():
    """Run the downloads cleanup every day at 00:00 UTC."""
    while True:
        now = datetime.now(timezone.utc)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        delay = max(1, (next_midnight - now).total_seconds())
        await asyncio.sleep(delay)
        try:
            await cleanup_downloads_once()
        except Exception as exc:
            print(f"[cleanup] scheduled cleanup failed: {exc}", flush=True)


def cleanup_old():
    """Remove download directories older than RETENTION_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
    active_dirs = active_job_dirs()
    dropped: list[str] = []

    for folder in DOWNLOAD_ROOT.iterdir():
        if not folder.is_dir():
            continue
        try:
            # A long download that outlives the retention window is still a
            # download; deleting the directory out from under the worker leaves
            # the job running against files that no longer exist.
            if folder.resolve() in active_dirs:
                continue
            modified = datetime.fromtimestamp(folder.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                dropped.append(folder.name)
        except FileNotFoundError:
            pass

    forget_jobs(dropped)


def forget_jobs(job_ids) -> None:
    """Drop jobs whose files have just been deleted.

    Without this the WebUI keeps listing a finished job whose media is gone, and
    every preview and download link on it 404s.
    """
    if not job_ids:
        return
    with jobs_lock:
        for job_id in job_ids:
            jobs.pop(job_id, None)
