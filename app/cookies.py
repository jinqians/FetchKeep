"""Cookie resolution for each supported platform.

Cookies are **server-side configuration** in Lite. There is no upload endpoint
and no WebUI for them: the operator either mounts a `cookies.txt` per platform
into COOKIES_DIR (or points `<PLATFORM>_COOKIE_FILE` at one), or inlines the jar
in the environment as `<PLATFORM>_COOKIES`, which `seed_cookies_from_env` writes
out at startup.

Keeping this off the frontend is the point: a Netscape cookie jar is a live
session for the account that exported it, and a public download page that
accepts one is a public page that collects them.
"""

import base64
import binascii
import os
from pathlib import Path

from app.config import (
    COOKIE_ENV_VARS,
    COOKIE_FILE,
    COOKIE_FILES,
    COOKIES_DIR,
)
from app.platform import platform_slug_for


def _has_cookie(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def cookie_file_for(url: str) -> Path | None:
    """The cookie file that applies to *url*, whether or not it exists."""
    slug = platform_slug_for(url)
    if slug == "instagram":
        # The generic cookies.txt is still honoured as an Instagram fallback:
        # it predates the per-platform files and is what older deployments have.
        for candidate in (COOKIE_FILES["instagram"], COOKIE_FILE):
            if _has_cookie(candidate):
                return candidate
        return COOKIE_FILES["instagram"]
    return COOKIE_FILES.get(slug)


def cookie_args_for(url: str) -> list[str]:
    """Return ``['--cookies', '<path>']`` when a valid cookie file exists."""
    path = cookie_file_for(url)
    if path is not None and _has_cookie(path):
        return ["--cookies", str(path)]
    return []


def cookie_status() -> dict[str, bool]:
    """Which platforms currently have a usable cookies.txt."""
    status = {name: _has_cookie(path) for name, path in COOKIE_FILES.items()}
    status["instagram"] = status["instagram"] or _has_cookie(COOKIE_FILE)
    return status


# ── Seeding from the environment ────────────────────────────────────────────

def _decode_cookie_value(raw: str) -> bytes | None:
    """Turn one `<PLATFORM>_COOKIES` value into cookie-file bytes.

    A Netscape jar is tab-separated and multi-line, which a `.env` file cannot
    carry literally, so three shapes are accepted and the check is on what the
    value decodes *to* rather than on how it was written:

      * base64 of the file (what a `.env` realistically holds),
      * the file itself, pasted with real newlines (compose YAML block scalar),
      * the file with `\\n` / `\\t` written as escapes.

    Returns None when nothing usable comes out, so a malformed value leaves any
    mounted file alone instead of truncating it.
    """
    value = (raw or "").strip()
    if not value:
        return None

    def looks_like_jar(text: str) -> bool:
        # Every real jar has tab-separated fields; the header is optional
        # because exporters disagree about it.
        return "\t" in text or "# Netscape" in text or "# HTTP Cookie File" in text

    # Base64 first: it is the only shape that cannot be confused with the
    # others, since a jar's tabs and '#' are outside the base64 alphabet.
    compact = "".join(value.split())
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        decoded = None
    if decoded:
        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if looks_like_jar(text):
            return text.encode("utf-8")

    text = value.replace("\\t", "\t").replace("\\r\\n", "\n").replace("\\n", "\n")
    if looks_like_jar(text):
        return (text if text.endswith("\n") else text + "\n").encode("utf-8")

    return None


def seed_cookies_from_env() -> dict[str, str]:
    """Materialise `<PLATFORM>_COOKIES` env values into COOKIE_FILES.

    The environment wins over whatever is on the volume: it is the declared
    configuration, and a stale file left over from a previous deployment is
    exactly what an operator setting the variable is trying to replace. An
    unchanged file is left untouched so its mtime keeps meaning something.

    Returns ``{platform: outcome}`` for the startup log.
    """
    report: dict[str, str] = {}

    for name, env_var in COOKIE_ENV_VARS.items():
        raw = os.getenv(env_var)
        if raw is None or not raw.strip():
            continue

        content = _decode_cookie_value(raw)
        target = COOKIE_FILES[name]
        if content is None:
            report[name] = f"{env_var} 无法识别为 Netscape cookies.txt，已忽略"
            continue

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and target.read_bytes() == content:
                report[name] = "unchanged"
                continue
            target.write_bytes(content)
            # The jar is a live session; nobody but this process needs to read it.
            os.chmod(target, 0o600)
            report[name] = f"written ({len(content)} bytes)"
        except OSError as exc:
            report[name] = f"写入 {target} 失败: {exc}"

    return report


def log_cookie_state() -> None:
    """Print what cookies the process starts with. No values, only presence."""
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    for name, outcome in seed_cookies_from_env().items():
        print(f"[cookies] {name}: {outcome}", flush=True)

    configured = sorted(name for name, ok in cookie_status().items() if ok)
    print(
        "[cookies] 已配置: " + (", ".join(configured) if configured else "（无）"),
        flush=True,
    )
