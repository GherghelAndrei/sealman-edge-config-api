"""Validation of an extension manifest's `endpoint_fields` section.

Each entry is a `FieldDefinition` an admin can later apply to endpoint types.
Contributed fields are never required. Kept free of `extensions.registry` and
`extensions.setup` imports so endpoint-type code can use it without a cycle.
"""

from typing import Any, Dict, Iterable, Optional

from pydantic import ValidationError as PydanticValidationError

from db.repos.extension import ExtensionRepository
from exceptions import APIError
from routers.schemas import normalize_field_definition


def validate_endpoint_fields(
    raw: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Returns the normalized definitions, or None when the section is absent.

    Raises APIError(422) for an invalid definition (including one that is not an
    object) or one with `required: true`.
    """
    if raw is None:
        return None

    normalized: Dict[str, Dict[str, Any]] = {}
    for key, definition in raw.items():
        try:
            normalized_definition = normalize_field_definition(definition)
        except PydanticValidationError as exc:
            raise APIError(f"Invalid endpoint field '{key}': {exc}", 422) from exc
        if normalized_definition.get("required"):
            raise APIError(f"Endpoint field '{key}' cannot be required", 422)
        normalized[key] = normalized_definition
    return normalized


async def validate_endpoint_field_ownership(
    extension_repo: ExtensionRepository, name: str, keys: Iterable[str]
) -> None:
    """Raises APIError(409) if another extension already declares one of `keys`.

    A field key belongs to one extension; `name`'s own stored keys are not a conflict.
    """
    owners: Dict[str, str] = {}
    for row in await extension_repo.list_extensions_rows():
        if row["name"] == name:
            continue
        for key in row.get("endpoint_fields") or {}:
            owners.setdefault(key, row["name"])
    for key in keys:
        owner = owners.get(key)
        if owner is not None:
            raise APIError(f"Endpoint field '{key}' is already declared by extension '{owner}'", 409)
