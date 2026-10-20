import pytest

from db.managed_fields import reject_roles_on_managed_fields
from exceptions import ValidationError


class TestRejectRolesOnManagedFields:
    def test_role_on_managed_field_is_rejected_with_message(self):
        with pytest.raises(ValidationError) as exc_info:
            reject_roles_on_managed_fields(
                {"title": "name", "serial_number": "ip"}, {"serial_number": "inventory"}
            )
        assert exc_info.value.status_code == 422
        assert str(exc_info.value) == (
            "'serial_number' is managed by extension 'inventory' and cannot have a role"
        )

    def test_role_on_unmanaged_field_is_allowed(self):
        reject_roles_on_managed_fields({"title": "name"}, {"serial_number": "inventory"})

    def test_empty_mapping_is_allowed(self):
        reject_roles_on_managed_fields({}, {"serial_number": "inventory"})
