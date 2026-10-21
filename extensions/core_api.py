"""Core routes on the internal side app that let an extension read Core data.

They live under `/core/extensions/{name}` so they cannot collide with an extension's
own `internal` routes. Auth is the extension's `X-Internal-Key` (same check as the
extension `internal` routes); the extension must also be enabled.

Must not import `extensions.setup` (it includes `core_router`), to avoid an import cycle.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from db.repos.endpoint import EndpointRepository
from db.repos.extension import ExtensionRepository
from db.session import get_repository
from helper import AuditTrail

from .runtime import verify_internal_key
from .schemas import InternalEndpoint

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


def managed_keys_by_type(types: List[Dict[str, Any]], extension: str) -> Dict[str, List[str]]:
    """{type_id: sorted keys managed by `extension`}, only for types with at least one such key."""
    result: Dict[str, List[str]] = {}
    for endpoint_type in types:
        keys = sorted(
            key for key, owner in (endpoint_type.get("managed_by") or {}).items() if owner == extension
        )
        if keys:
            result[endpoint_type["type_id"]] = keys
    return result


def project_endpoint(row: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """The `InternalEndpoint` shape of a raw endpoint row, with only the stored values of `keys`."""
    stored = row["endpoint_data"]
    return {
        "endpoint_id": row["endpoint_id"],
        "device_id": row["device_id"],
        "type_id": row["type_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "data": {key: stored[key] for key in keys if key in stored},
    }


@core_router.get("/devices/{device_id}/endpoints", response_model=List[InternalEndpoint])
async def get_device_endpoints(
    name: str,
    device_id: str,
    caller: Dict[str, Any] = Depends(core_extension_caller),
    endpoint_repo: EndpointRepository = Depends(get_repository(EndpointRepository)),
) -> List[Dict[str, Any]]:
    """The device's endpoints whose type has at least one field managed by this extension, with
    only those fields' stored values. Ordered by `created_at`, then `endpoint_id`."""
    keys_by_type = managed_keys_by_type(await endpoint_repo.get_endpoint_types(), name)
    rows = await endpoint_repo.get_endpoints_by_types(device_id, list(keys_by_type))
    return [project_endpoint(row, keys_by_type[row["type_id"]]) for row in rows]
