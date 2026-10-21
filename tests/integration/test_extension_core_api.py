"""Internal Core routes that let an extension read its own endpoint field values (port 8500)."""
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Optional
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.endpoint_fixtures import _endpoint_repo, seed_endpoint
from tests.integration.extension_fixtures import (
    STRING_FIELD,
    seed_keyed_extension,
    set_endpoint_created_at,
)
from tests.integration.test_abac_authorization import AbacFixtures

DEVICE = "core-api-dev"
OTHER_DEVICE = "core-api-dev-2"
NOTE_FIELD = {"type": "string", "label": "Note"}


@pytest.fixture
async def internal_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Like `client`, but on the internal side app; only `get_db` is overridden."""
    from db.session import get_db
    from extensions.setup import internal_app

    async def _override_get_db():
        yield db_session

    internal_app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=internal_app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal") as ac:
        yield ac
    internal_app.dependency_overrides.clear()


def _label() -> str:
    return f"core-{uuid4().hex[:8]}"


def _at(day: int, month: int = 1) -> datetime:
    return datetime(2026, month, day, tzinfo=timezone.utc)


async def _type(db_session, fields: Dict, managed_by: Optional[Dict[str, str]] = None) -> str:
    created = await _endpoint_repo(db_session).create_endpoint_type(
        label=_label(), description=None, fields=fields, mapping={}, managed_by=managed_by or {}
    )
    return created["type_id"]


async def _devices(db_session, *device_ids: str) -> None:
    await AbacFixtures(db_session).setup(devices={d: {} for d in device_ids})


async def _get_device(internal_client, name: str, key: Optional[str], device_id: str = DEVICE):
    headers = {"X-Internal-Key": key} if key is not None else {}
    return await internal_client.get(
        f"/core/extensions/{name}/devices/{device_id}/endpoints", headers=headers
    )


class TestCoreAuth:
    async def test_missing_and_invalid_key_are_401(self, internal_client, db_session):
        name, _ = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})

        missing = await _get_device(internal_client, name, None)
        assert missing.status_code == 401, missing.text
        assert missing.json()["detail"] == "Missing X-Internal-Key"

        invalid = await _get_device(internal_client, name, "wrong")
        assert invalid.status_code == 401, invalid.text
        assert invalid.json()["detail"] == "Invalid X-Internal-Key"

    async def test_key_of_another_extension_is_401(self, internal_client, db_session):
        name_a, key_a = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        name_b, _ = await seed_keyed_extension(db_session, {"asset_tag": STRING_FIELD})

        response = await _get_device(internal_client, name_b, key_a)
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "Invalid X-Internal-Key"

    async def test_disabled_extension_is_403(self, internal_client, db_session):
        name, key = await seed_keyed_extension(
            db_session, {"serial_number": STRING_FIELD}, enabled=False
        )

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == f"Extension '{name}' is disabled"

    async def test_success_is_audited_as_extension(self, internal_client, db_session, monkeypatch):
        from helper import AuditTrail

        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        entries = []

        async def fake_log(user, access, method=None):
            entries.append((user, access))

        monkeypatch.setattr(AuditTrail, "log", fake_log)

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert entries and entries[0][0] == f"extension:{name}"

    async def test_not_served_on_public_app(self, client):
        response = await client.get("/core/extensions/x/devices/d/endpoints")
        assert response.status_code == 404, response.text


class TestPerDevice:
    async def test_only_types_with_own_managed_fields(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        own = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": name})
        plain = await _type(db_session, {"serial_number": STRING_FIELD})
        foreign = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": "other"})
        own_ep = await seed_endpoint(db_session, DEVICE, own, {"serial_number": "SN-1"})
        await seed_endpoint(db_session, DEVICE, plain, {"serial_number": "SN-2"})
        await seed_endpoint(db_session, DEVICE, foreign, {"serial_number": "SN-3"})

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert [e["endpoint_id"] for e in response.json()] == [own_ep]

    async def test_data_holds_only_own_managed_keys(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        type_id = await _type(
            db_session,
            {"serial_number": STRING_FIELD, "asset_tag": STRING_FIELD, "note": NOTE_FIELD},
            {"serial_number": name, "asset_tag": "other"},
        )
        await seed_endpoint(
            db_session, DEVICE, type_id, {"serial_number": "SN-1", "asset_tag": "AT-1", "note": "n"}
        )

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert [e["data"] for e in response.json()] == [{"serial_number": "SN-1"}]

    async def test_absent_value_is_omitted(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        with_default = {**STRING_FIELD, "default": "SN-DEFAULT"}
        type_id = await _type(
            db_session, {"serial_number": with_default, "note": NOTE_FIELD}, {"serial_number": name}
        )
        await seed_endpoint(db_session, DEVICE, type_id, {"note": "n"})

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert [e["data"] for e in response.json()] == [{}]

    async def test_endpoints_ordered_by_created_at_asc(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        type_id = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": name})
        late = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "late"})
        early = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "early"})
        tie_a = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "tie-a"})
        tie_b = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "tie-b"})
        await set_endpoint_created_at(db_session, late, _at(3))
        await set_endpoint_created_at(db_session, early, _at(1))
        await set_endpoint_created_at(db_session, tie_a, _at(2))
        await set_endpoint_created_at(db_session, tie_b, _at(2))

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert [e["endpoint_id"] for e in response.json()] == [early, *sorted([tie_a, tie_b]), late]

    async def test_timestamps_and_ids_present(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        type_id = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": name})
        endpoint_id = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "SN-1"})

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        [item] = response.json()
        assert item["endpoint_id"] == endpoint_id
        assert item["device_id"] == DEVICE
        assert item["type_id"] == type_id
        datetime.fromisoformat(item["created_at"])
        datetime.fromisoformat(item["updated_at"])
        assert set(item) == {"endpoint_id", "device_id", "type_id", "created_at", "updated_at", "data"}

    async def test_unknown_device_is_empty_list(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})

        response = await _get_device(internal_client, name, key, device_id="no-such-device")
        assert response.status_code == 200, response.text
        assert response.json() == []

    async def test_other_devices_excluded(self, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE, OTHER_DEVICE)
        type_id = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": name})
        mine = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "SN-1"})
        await seed_endpoint(db_session, OTHER_DEVICE, type_id, {"serial_number": "SN-2"})

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert [e["endpoint_id"] for e in response.json()] == [mine]

    async def test_released_field_hides_endpoint(self, client, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        created = await client.post(
            "/endpoint-types",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert created.status_code == 201, created.text
        type_id = created.json()["type_id"]
        endpoint_id = await seed_endpoint(db_session, DEVICE, type_id, {"serial_number": "SN-1"})
        assert len((await _get_device(internal_client, name, key)).json()) == 1

        released = await client.patch(
            f"/endpoint-types/{type_id}", json={"fields": {"serial_number": None}}
        )
        assert released.status_code == 200, released.text

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert response.json() == []
        endpoint = await client.get(f"/endpoints/{endpoint_id}")
        assert endpoint.json()["endpoint_data"]["serial_number"] == {"value": "SN-1", "field": None}

    async def test_retyped_endpoint_leaves_scope(self, client, internal_client, db_session):
        name, key = await seed_keyed_extension(db_session, {"serial_number": STRING_FIELD})
        await _devices(db_session, DEVICE)
        managed = await _type(db_session, {"serial_number": STRING_FIELD}, {"serial_number": name})
        plain = await _type(db_session, {"note": NOTE_FIELD})
        endpoint_id = await seed_endpoint(db_session, DEVICE, managed, {"serial_number": "SN-1"})
        assert len((await _get_device(internal_client, name, key)).json()) == 1

        retyped = await client.patch(f"/endpoints/{endpoint_id}", json={"type_id": plain})
        assert retyped.status_code == 200, retyped.text

        response = await _get_device(internal_client, name, key)
        assert response.status_code == 200, response.text
        assert response.json() == []
