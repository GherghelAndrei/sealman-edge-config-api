from unittest.mock import AsyncMock

import pytest

from exceptions import APIError
from extensions.endpoint_fields import validate_endpoint_fields
from extensions.registry import _build_detail


def test_none_means_absent():
    assert validate_endpoint_fields(None) is None


def test_normalizes_definitions():
    result = validate_endpoint_fields({"serial_number": {"type": "string", "label": "S"}})
    assert result["serial_number"]["ui"] == "input"
    assert result["serial_number"]["required"] is False
    assert "validation" not in result["serial_number"]
    assert "options" not in result["serial_number"]
    assert "description" not in result["serial_number"]


def test_empty_object_stays_empty():
    assert validate_endpoint_fields({}) == {}


def test_required_true_is_422():
    with pytest.raises(APIError) as exc_info:
        validate_endpoint_fields({"serial_number": {"type": "string", "label": "S", "required": True}})
    assert exc_info.value.status_code == 422
    assert str(exc_info.value) == "Endpoint field 'serial_number' cannot be required"


def test_invalid_definition_is_422():
    with pytest.raises(APIError) as exc_info:
        validate_endpoint_fields({"x": {"type": "string"}})
    assert exc_info.value.status_code == 422
    assert str(exc_info.value).startswith("Invalid endpoint field 'x'")


@pytest.mark.parametrize("definition", ["string", ["string"], 1, None])
def test_non_object_definition_is_422(definition):
    with pytest.raises(APIError) as exc_info:
        validate_endpoint_fields({"serial_number": definition})
    assert exc_info.value.status_code == 422
    assert str(exc_info.value).startswith("Invalid endpoint field 'serial_number'")


@pytest.mark.asyncio
async def test_build_detail_defaults_endpoint_fields():
    extension_repo = AsyncMock()
    extension_repo.get_extension_row.return_value = {
        "name": "inventory",
        "description": "",
        "schema_version": 1,
        "enabled": False,
    }
    extension_repo.list_upstreams.return_value = []
    extension_repo.list_routes.return_value = []
    extension_repo.list_extension_action_specs.return_value = []

    detail = await _build_detail(extension_repo, "inventory")

    assert detail.endpoint_fields == {}
