"""Validation of an extension manifest's `endpoint_fields` section.

Each entry is a `FieldDefinition` an admin can later apply to endpoint types.
Contributed fields are never required. Kept free of `extensions.registry` and
`extensions.setup` imports so endpoint-type code can use it without a cycle.
"""

from typing import Any, Dict, Optional

from pydantic import ValidationError as PydanticValidationError

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
