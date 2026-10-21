"""Core routes on the internal side app that let an extension read Core data.

They live under `/core/extensions/{name}` so they cannot collide with an extension's
own `internal` routes. Auth is the extension's `X-Internal-Key` (same check as the
extension `internal` routes); the extension must also be enabled.

Must not import `extensions.setup` (it includes `core_router`), to avoid an import cycle.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from db.repos.extension import ExtensionRepository
from db.session import get_repository
from helper import AuditTrail

from .runtime import verify_internal_key

core_router = APIRouter(prefix="/core/extensions/{name}")


async def core_extension_caller(
    name: str,
    request: Request,
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
    extension_repo: ExtensionRepository = Depends(get_repository(ExtensionRepository)),
) -> Dict[str, Any]:
    """Authenticates the calling extension and returns its row. 401 for a missing or
    wrong key (including another extension's key), 403 for a disabled extension."""
    row = await verify_internal_key(request, name, x_internal_key, extension_repo)
    if not row["enabled"]:
        access = f"internal {request.method} {request.url.path}"
        await AuditTrail.log(f"extension:{name}", f"{access} rejected: extension disabled")
        raise HTTPException(status_code=403, detail=f"Extension '{name}' is disabled")
    return row
