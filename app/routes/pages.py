"""Page routes: serve the frontend SPA."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.config import STATIC_DIR

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")
