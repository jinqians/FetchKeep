"""Media processing: codec probing, remux, transcode, preview generation."""

import hashlib
import subprocess
from pathlib import Path

from app.config import (
    ARCHIVE_DIRNAME,
    AUDIO_SUFFIXES,
    BROWSER_AUDIO_CODECS,
    BROWSER_CONTAINERS,
    BROWSER_VIDEO_CODECS,
    IMAGE_SUFFIXES,
    PARTIAL_SUFFIXES,
    VIDEO_SUFFIXES,
)

# Job-internal directories: never part of the file listing the WebUI shows.
INTERNAL_DIRS = {".previews", ARCHIVE_DIRNAME}


# ── Codec probing ───────────────────────────────────────────────────────────

def probe_codecs(video: Path) -> tuple[str, str]:
    """Return the (video, audio) codec names of a media file, best effort."""
    def one(stream: str) -> str:
        try:
            proc = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", stream,
                    "-show_entries", "stream=codec_name",
                    "-of", "default=nw=1:nk=1",
                    str(video),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        out = proc.stdout.strip()
        return out.splitlines()[0] if out else ""

    return one("v:0"), one("a:0")


def is_browser_playable(video: Path, video_codec: str, audio_codec: str) -> bool:
    """Check whether a browser can play the video inline."""
    return (
        video.suffix.lower() in BROWSER_CONTAINERS
        and video_codec in BROWSER_VIDEO_CODECS
        and audio_codec in BROWSER_AUDIO_CODECS
    )


# ── Remux / transcode ──────────────────────────────────────────────────────

def remux_faststart(video: Path) -> Path:
    """Move the MP4 index to the front so the browser can start playing early.

    This is a stream copy: no re-encoding, so media quality and CPU cost stay
    negligible. Any failure leaves the original file untouched.
    """
    if video.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        return video

    tmp = video.with_name(video.stem + ".faststart.tmp.mp4")
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", str(video),
                "-map", "0",
                "-c", "copy",
                "-movflags", "+faststart",
                "-y", str(tmp),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        tmp.unlink(missing_ok=True)
        return video

    if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.replace(video)
    else:
        tmp.unlink(missing_ok=True)
    return video


def transcode_to_h264(video: Path) -> Path:
    """Re-encode a video to H.264/AAC MP4. CPU heavy: only ever run on demand."""
    tmp = video.with_name(video.stem + ".browser.tmp.mp4")
    target = video.with_suffix(".mp4")
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", str(video),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-y", str(tmp),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=6 * 3600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"转码失败：{exc}") from exc

    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        raise RuntimeError("转码失败：" + ("\n".join(tail) or "ffmpeg 返回错误"))

    tmp.replace(target)
    if target != video:
        video.unlink(missing_ok=True)
    return target


# ── Preview generation ──────────────────────────────────────────────────────

def generate_video_preview(video: Path, job_dir: Path) -> Path | None:
    """Create a lightweight JPEG poster for browser preview.

    The poster is kept under .previews and is never exposed as a downloadable
    job item. This makes AV1/WebM/other browser-incompatible videos still
    visually previewable.
    """
    preview_dir = job_dir / ".previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    # A digest rather than hash(): PYTHONHASHSEED is randomised per process, so
    # hash() would name the same video differently after every restart and the
    # cache check below could never hit.
    safe_id = hashlib.sha1(video.as_posix().encode("utf-8")).hexdigest()[:16]
    preview = preview_dir / f"{safe_id}.jpg"
    if preview.exists() and preview.stat().st_size > 0:
        return preview

    for seek in ("1", "0"):
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-ss", seek, "-i", str(video),
                    "-frames:v", "1",
                    "-vf", "scale=480:-2:force_original_aspect_ratio=decrease",
                    "-q:v", "4", "-y", str(preview),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            if proc.returncode == 0 and preview.exists() and preview.stat().st_size > 0:
                return preview
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


# ── File helpers ────────────────────────────────────────────────────────────

def is_partial(p: Path) -> bool:
    """Whether *p* is a fragment a download tool left behind, not a result."""
    # yt-dlp also writes `video.mp4.part-Frag12`, which .suffix reports as
    # ".part-Frag12" rather than ".part".
    suffix = p.suffix.lower()
    return suffix in PARTIAL_SUFFIXES or suffix.startswith(".part-")


def collect_files(folder: Path) -> list[Path]:
    """Collect finished downloads in *folder*, excluding internal items.

    Partial files are excluded on purpose. "Did this run produce files?" is the
    question every fallback in downloader.py turns on, and a `.part` from a
    connection that dropped would answer it "yes" — skipping the fallback and
    publishing a truncated video as the result.
    """
    return [
        p for p in folder.rglob("*")
        if p.is_file()
        and p.name != ".gitkeep"
        and not INTERNAL_DIRS.intersection(p.parts)
        and not is_partial(p)
    ]


def clear_partials(folder: Path) -> None:
    """Wipe what a failed attempt left behind before the next one runs.

    Deliberately does *not* go through collect_files: that one hides the `.part`
    files, and the whole point here is to delete them. Anything the previous
    attempt wrote is fair game, because the attempt failed — if it had not, the
    caller would have stopped rather than reached this.
    """
    folder = Path(folder)
    for leftover in folder.rglob("*"):
        if not leftover.is_file() or leftover.name == ".gitkeep":
            continue
        if INTERNAL_DIRS.intersection(leftover.parts):
            continue
        try:
            leftover.unlink()
        except OSError:
            pass


def build_file_item(p: Path, job_dir: Path, remux: bool = True) -> dict | None:
    """Describe one downloaded file for the WebUI."""
    suffix = p.suffix.lower()
    kind = (
        "image" if suffix in IMAGE_SUFFIXES
        else "video" if suffix in VIDEO_SUFFIXES
        else "audio" if suffix in AUDIO_SUFFIXES
        else "file"
    )

    if kind == "video" and remux:
        # Stream copy only: moves the MP4 index to the front so playback can
        # start before the whole file is fetched. No re-encoding, so this stays
        # cheap even for 4K. Transcoding is a separate, on-demand action.
        p = remux_faststart(p)

    try:
        rel = p.relative_to(job_dir).as_posix()
    except ValueError:
        return None

    item = {
        "path": rel,
        "name": p.name,
        "size": p.stat().st_size,
        "kind": kind,
    }

    if kind == "video":
        video_codec, audio_codec = probe_codecs(p)
        item["vcodec"] = video_codec
        item["acodec"] = audio_codec
        item["browser_playable"] = is_browser_playable(p, video_codec, audio_codec)
        preview = generate_video_preview(p, job_dir)
        if preview:
            item["preview"] = preview.relative_to(job_dir).as_posix()

    return item
