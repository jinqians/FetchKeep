"""Quality probing endpoint."""

import asyncio

from fastapi import APIRouter, Form, HTTPException

from app.jobs import probe_executor
from app.platform import detect_engine
from app.quality import probe_formats
from app.routes._helpers import validate_url

router = APIRouter()


@router.post("/api/probe")
async def probe(url: str = Form(...)):
    """List the qualities that actually exist for a URL, before downloading."""
    url = validate_url(url)

    if detect_engine(url) == "gallery-dl":
        return {
            "supported": False,
            "reason": "该链接由 gallery-dl 处理（图片/图集），没有画质可选。",
        }

    try:
        return await asyncio.get_running_loop().run_in_executor(
            probe_executor, probe_formats, url
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
