from typing import List

from fastapi import APIRouter, Depends

from authorization.abac_permission_check import ABACPermissionCheck
from authorization.permission_types import Platform
from db.repos.endpoint import EndpointRepository
from db.repos.extension import ExtensionRepository
from db.session import get_repository
from extensions.endpoint_fields import list_extension_field_sets
from routers.extension_fields.schemas import ExtensionFieldSet

# Always registered, also with EXTENSIONS_ENABLED=false: the declared fields are stored data.
extension_fields = APIRouter()

_read = Depends(ABACPermissionCheck(Platform.CONFIG_READ, device_path=None))
_write = Depends(ABACPermissionCheck(Platform.CONFIG_WRITE, device_path=None))


@extension_fields.get(
    "/extension-fields",
    response_model=List[ExtensionFieldSet],
    tags=["Extension Fields"],
    summary="List declared extension fields and where they are applied",
)
async def list_extension_fields(
    extension_repo: ExtensionRepository = Depends(get_repository(ExtensionRepository)),
    endpoint_repo: EndpointRepository = Depends(get_repository(EndpointRepository)),
    _auth=_read,
):
    """Lists the extensions that declare endpoint fields, and the types each field is applied to."""
    return await list_extension_field_sets(extension_repo, endpoint_repo)
