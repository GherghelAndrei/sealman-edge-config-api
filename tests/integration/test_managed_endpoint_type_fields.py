"""Endpoint types carry a `managed_by` marker ({field_key: extension}) for extension fields."""
from uuid import uuid4

from db.registry import repo_registry
from db.repos.endpoint import EndpointRepository

SERIAL_FIELD = {
    "type": "string",
    "label": "Serial",
    "required": False,
    "ui": "input",
    "changeable": True,
    "show_in_list": True,
}


def _label() -> str:
    return f"et-{uuid4().hex[:8]}"


class TestManagedByMarker:
    async def test_new_type_has_empty_managed_by(self, client):
        created = await client.post("/endpoint-types", json={"label": _label()})
        assert created.status_code == 201, created.text
        assert created.json()["managed_by"] == {}

        response = await client.get(f"/endpoint-types/{created.json()['type_id']}")
        assert response.status_code == 200, response.text
        assert response.json()["managed_by"] == {}

    async def test_repo_create_stores_managed_by(self, client, db_session):
        repo = repo_registry.get(EndpointRepository)(db_session)
        created = await repo.create_endpoint_type(
            label=_label(),
            description=None,
            fields={"serial_number": SERIAL_FIELD},
            mapping={},
            managed_by={"serial_number": "inventory"},
        )
        assert created["managed_by"] == {"serial_number": "inventory"}

        response = await client.get(f"/endpoint-types/{created['type_id']}")
        assert response.status_code == 200, response.text
        assert response.json()["managed_by"] == {"serial_number": "inventory"}

    async def test_type_list_includes_managed_by(self, client):
        created = await client.post("/endpoint-types", json={"label": _label()})
        assert created.status_code == 201, created.text

        response = await client.get("/endpoint-types")
        assert response.status_code == 200, response.text
        listed = {t["type_id"]: t for t in response.json()}
        assert listed[created.json()["type_id"]]["managed_by"] == {}

    async def test_patch_ignores_sent_managed_by(self, client):
        created = await client.post("/endpoint-types", json={"label": _label()})
        assert created.status_code == 201, created.text

        response = await client.patch(
            f"/endpoint-types/{created.json()['type_id']}",
            json={"label": _label(), "managed_by": {"x": "y"}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["managed_by"] == {}
