"""Route registration: collect all APIRouters and expose ``include_routers``.

The public routers carry no cookie settings. Cookie jars are live sessions for
the accounts that exported them, and an open download page that accepts uploads
is an open page that collects them — so uploading one is an admin action, behind
the token in app.auth, and every other way of configuring them is server-side
(see app.cookies).
"""

from app.routes.admin import router as admin_router
from app.routes.download import router as download_router
from app.routes.health import router as health_router
from app.routes.pages import router as pages_router
from app.routes.probe import router as probe_router
from app.routes.transcode import router as transcode_router

__all__ = ["include_routers"]

_routers = [
    pages_router,
    health_router,
    probe_router,
    download_router,
    transcode_router,
    admin_router,
]


def include_routers(app):
    """Register every sub-router on *app*."""
    for r in _routers:
        app.include_router(r)
