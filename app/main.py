"""FetchKeep-Lite application entry point.

All business logic lives in sibling modules; this file only wires up the
FastAPI instance, mounts static assets, registers routes, and starts
background tasks.

Start with:  uvicorn app.main:app --host 0.0.0.0 --port 9080
"""

import asyncio
import contextlib
import threading
import time
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import startup_banner
from app.cleanup import cleanup_old, downloads_cleanup_loop
from app.config import STATIC_DIR
from app.cookies import log_cookie_state
from app.routes import include_routers

app = FastAPI(title="FetchKeep Lite", version="8.2")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

include_routers(app)

# Background tasks, kept referenced. asyncio holds only a weak reference to a
# task, so a create_task() whose result is dropped can be garbage collected
# mid-await and the cleanup loop would simply stop running.
_background_tasks: set[asyncio.Task] = set()


@app.on_event("startup")
def startup():
    # Cookies are server-side configuration: materialise anything provided
    # through the environment before the first download can ask for it.
    log_cookie_state()
    startup_banner()

    task = asyncio.get_running_loop().create_task(downloads_cleanup_loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    def cleaner():
        while True:
            time.sleep(3600)
            with contextlib.suppress(Exception):
                cleanup_old()

    threading.Thread(target=cleaner, daemon=True).start()
