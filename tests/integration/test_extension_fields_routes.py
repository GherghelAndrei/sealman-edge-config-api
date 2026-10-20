"""`/extension-fields` routes: the fields extensions declare and the types they are applied to."""
import pytest

from tests.integration.endpoint_fixtures import _endpoint_repo, unique_label
from tests.integration.extension_fixtures import STRING_FIELD, seed_extension
from tests.integration.test_abac_authorization import AbacFixtures

USER_OID = "extension-fields-perm-oid"


def _find(listing, name):
    return next((item for item in listing if item["extension"] == name), None)


async def _seed_managed_type(db_session, extension: str) -> str:
    created = await _endpoint_repo(db_session).create_endpoint_type(
        label=unique_label("et"),
        description=None,
        fields={"serial_number": STRING_FIELD},
        mapping={},
        managed_by={"serial_number": extension},
    )
    return created["type_id"]


class TestListExtensionFields:
    async def test_lists_only_extensions_with_fields(self, client, db_session):
        with_fields = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        without_fields = await seed_extension(db_session, {})

        response = await client.get("/extension-fields")
        assert response.status_code == 200, response.text
        listing = response.json()

        item = _find(listing, with_fields)
        assert item is not None
        assert item["enabled"] is True
        assert item["fields"]["serial_number"]["label"] == "Serial number"
        assert item["applied"] == {"serial_number": []}
        assert _find(listing, without_fields) is None

    async def test_applied_lists_types_managed_by_the_extension(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD, "batch": STRING_FIELD})
        type_id = await _seed_managed_type(db_session, name)
        await _seed_managed_type(db_session, "someone_else")

        response = await client.get("/extension-fields")
        assert response.status_code == 200, response.text
        item = _find(response.json(), name)
        assert item["applied"] == {"serial_number": [type_id], "batch": []}

    async def test_applied_type_ids_are_sorted(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_ids = [await _seed_managed_type(db_session, name) for _ in range(3)]

        response = await client.get("/extension-fields")
        item = _find(response.json(), name)
        assert item["applied"]["serial_number"] == sorted(type_ids)

    async def test_disabled_extension_listed_with_enabled_false(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD}, enabled=False)

        response = await client.get("/extension-fields")
        assert response.status_code == 200, response.text
        item = _find(response.json(), name)
        assert item is not None
        assert item["enabled"] is False

    async def test_ordered_by_extension_name(self, client, db_session):
        await seed_extension(db_session, {"serial_number": STRING_FIELD})
        await seed_extension(db_session, {"batch": STRING_FIELD})

        names = [item["extension"] for item in (await client.get("/extension-fields")).json()]
        assert names == sorted(names)


class TestExtensionFieldsReadPermissions:
    @pytest.fixture
    def fake_jwt_user(self):
        return {
            "oid": USER_OID,
            "sub": USER_OID,
            "preferred_username": "extension-fields-perm@test.com",
            "name": "Extension Fields Perm",
            "roles": [],
        }

    async def _grant(self, db_session, *actions):
        await AbacFixtures(db_session).setup(
            users={"tester": USER_OID},
            roles={"r": list(actions)},
            teams={"t": {"roles": ["r"], "users": ["tester"]}},
        )

    async def test_platform_config_read_can_list(self, client, db_session):
        await self._grant(db_session, "platform.config.read")
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})

        response = await client.get("/extension-fields")
        assert response.status_code == 200, response.text
        assert _find(response.json(), name) is not None

    async def test_endpoint_read_alone_cannot_list(self, client, db_session):
        await self._grant(db_session, "device.endpoint.read")
        assert (await client.get("/extension-fields")).status_code == 403
