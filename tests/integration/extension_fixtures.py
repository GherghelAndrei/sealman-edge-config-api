"""Shared helpers for the extension-fields integration tests."""
from typing import Dict, Optional
from uuid import uuid4

from db.registry import repo_registry
from db.repos.extension import ExtensionRepository

STRING_FIELD = {"type": "string", "label": "Serial number"}


def unique_extension_name(prefix: str = "inventory") -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def manifest(name: str, endpoint_fields: Optional[Dict] = None) -> dict:
    body = {"schema_version": 1, "name": name, "upstreams": {}, "routes": []}
    if endpoint_fields is not None:
        body["endpoint_fields"] = endpoint_fields
    return body


async def seed_extension(session, endpoint_fields: Dict[str, Dict], enabled: bool = True) -> str:
    """Creates an extension row directly through the repository and returns its unique name."""
    name = unique_extension_name()
    repo = repo_registry.get(ExtensionRepository)(session)
    await repo.create_extension(name, "", 1)
    await repo.set_endpoint_fields(name, endpoint_fields)
    await repo.set_enabled(name, enabled)
    return name
