"""Rules for endpoint-type fields managed by an extension (`managed_by`: {field_key: extension}).

A managed field's definition comes from the extension's manifest. It cannot carry a role: roles
come from admin fields only. Once a field stops being managed it is a normal field again.
"""
from typing import Mapping

from exceptions import ValidationError


def reject_roles_on_managed_fields(
    mapping: Mapping[str, str], managed_by: Mapping[str, str]
) -> None:
    """Raises ValidationError (422) for the first mapping key that is a managed field."""
    for field_key in mapping:
        extension = managed_by.get(field_key)
        if extension is not None:
            raise ValidationError(
                f"'{field_key}' is managed by extension '{extension}' and cannot have a role", 422
            )
