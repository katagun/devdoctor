from __future__ import annotations

import shutil

from fastapi import APIRouter
from starlette.responses import JSONResponse

router = APIRouter(prefix="/api")

# Root volume — on macOS and most Linux desktops this is where $HOME lives
# and where every provider's cleanups land. Using a fixed path (rather than
# $HOME's device) keeps the number reported here comparable across providers.
_MOUNT = "/"


@router.get("/disk-usage")
def disk_usage() -> JSONResponse:
    u = shutil.disk_usage(_MOUNT)
    return JSONResponse(
        content={
            "mount": _MOUNT,
            "total_bytes": u.total,
            "used_bytes": u.used,
            "free_bytes": u.free,
        }
    )
