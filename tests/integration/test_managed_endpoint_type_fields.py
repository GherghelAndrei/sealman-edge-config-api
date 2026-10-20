"""Endpoint types carry a `managed_by` marker ({field_key: extension}) for extension fields."""
from uuid import uuid4

import pytest

from db.registry import repo_registry
from db.repos.endpoint import EndpointRepository
from db.repos.extension import ExtensionRepository

from tests.integration.endpoint_fixtures import _endpoint_repo, seed_endpoint_type
from tests.integration.extension_fixtures import STRING_FIELD, seed_extension
from tests.integration.test_abac_authorization import AbacFixtures

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


# --- extension_fields on type create and type PATCH (D23, D24) -------------------------------

ROLE_MESSAGE = "'serial_number' is managed by extension '{}' and cannot have a role"
NOTE_FIELD = {"type": "string", "label": "Note"}


async def _assert_stored_copy(db_session, type_id: str, extension: str, key: str) -> None:
    """The type's stored definition equals the extension's stored manifest definition."""
    db_session.expire_all()
    row = await repo_registry.get(ExtensionRepository)(db_session).get_extension_row(extension)
    stored_type = await _endpoint_repo(db_session).get_endpoint_type(type_id)
    assert stored_type["fields"][key] == row["endpoint_fields"][key]


async def _labels(client) -> set:
    return {t["label"] for t in (await client.get("/endpoint-types")).json()}


class TestCreateWithExtensionFields:
    async def test_create_copies_selected_fields_as_managed(self, client, db_session):
        name = await seed_extension(
            db_session, {"serial_number": STRING_FIELD, "batch": STRING_FIELD}
        )
        response = await client.post(
            "/endpoint-types",
            json={
                "label": _label(),
                "fields": {"note": NOTE_FIELD},
                "extension_fields": {name: ["serial_number"]},
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        await _assert_stored_copy(db_session, body["type_id"], name, "serial_number")
        assert "batch" not in body["fields"]
        assert body["fields"]["note"]["label"] == "Note"
        assert body["managed_by"] == {"serial_number": name}

    async def test_create_role_on_extension_field_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        label = _label()
        response = await client.post(
            "/endpoint-types",
            json={
                "label": label,
                "extension_fields": {name: ["serial_number"]},
                "mapping": {"serial_number": "name"},
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == ROLE_MESSAGE.format(name)
        assert label not in await _labels(client)

    async def test_create_clash_with_fields_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        label = _label()
        response = await client.post(
            "/endpoint-types",
            json={
                "label": label,
                "fields": {"serial_number": NOTE_FIELD},
                "extension_fields": {name: ["serial_number"]},
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == "'serial_number' is in both fields and extension_fields"
        assert label not in await _labels(client)

    async def test_create_disabled_extension_is_409(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD}, enabled=False)
        label = _label()
        response = await client.post(
            "/endpoint-types",
            json={"label": label, "extension_fields": {name: ["serial_number"]}},
        )
        assert response.status_code == 409, response.text
        assert response.json()["message"] == (
            f"Extension '{name}' is disabled; enable it to apply its fields"
        )
        assert label not in await _labels(client)

    async def test_create_unknown_extension_or_key_is_404(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        label = _label()

        unknown_ext = await client.post(
            "/endpoint-types",
            json={"label": label, "extension_fields": {"missing_ext": ["serial_number"]}},
        )
        assert unknown_ext.status_code == 404, unknown_ext.text
        assert unknown_ext.json()["message"] == "Extension 'missing_ext' not found"

        unknown_key = await client.post(
            "/endpoint-types",
            json={"label": label, "extension_fields": {name: ["nope"]}},
        )
        assert unknown_key.status_code == 404, unknown_key.text
        assert unknown_key.json()["message"] == f"Extension '{name}' declares no endpoint field 'nope'"
        assert label not in await _labels(client)

    async def test_create_without_extension_fields_unchanged(self, client):
        response = await client.post(
            "/endpoint-types", json={"label": _label(), "fields": {"note": NOTE_FIELD}}
        )
        assert response.status_code == 201, response.text
        assert response.json()["managed_by"] == {}
        assert set(response.json()["fields"]) == {"note"}


class TestPatchWithExtensionFields:
    async def test_patch_adds_extension_fields_with_field_edits_in_one_request(
        self, client, db_session
    ):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(db_session)
        new_label = _label()

        response = await client.patch(
            f"/endpoint-types/{type_id}",
            json={
                "label": new_label,
                "fields": {"note": NOTE_FIELD},
                "extension_fields": {name: ["serial_number"]},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["label"] == new_label
        assert set(body["fields"]) == {"note", "serial_number"}
        await _assert_stored_copy(db_session, type_id, name, "serial_number")
        assert body["managed_by"] == {"serial_number": name}

    async def _assert_unchanged(self, client, type_id, before):
        after = (await client.get(f"/endpoint-types/{type_id}")).json()
        assert after == before

    async def test_patch_key_already_on_type_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(
            db_session, fields={"serial_number": {"type": "string", "label": "Mine"}}
        )
        before = (await client.get(f"/endpoint-types/{type_id}")).json()

        response = await client.patch(
            f"/endpoint-types/{type_id}",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == "'serial_number' already exists on this type"
        await self._assert_unchanged(client, type_id, before)

    async def test_patch_clash_with_fields_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(db_session)
        before = (await client.get(f"/endpoint-types/{type_id}")).json()

        response = await client.patch(
            f"/endpoint-types/{type_id}",
            json={
                "label": _label(),
                "fields": {"serial_number": NOTE_FIELD},
                "extension_fields": {name: ["serial_number"]},
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == "'serial_number' is in both fields and extension_fields"
        await self._assert_unchanged(client, type_id, before)

    async def test_patch_disabled_extension_is_409(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD}, enabled=False)
        type_id = await seed_endpoint_type(db_session)
        before = (await client.get(f"/endpoint-types/{type_id}")).json()

        response = await client.patch(
            f"/endpoint-types/{type_id}",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert response.status_code == 409, response.text
        await self._assert_unchanged(client, type_id, before)

    async def test_patch_unknown_extension_or_key_is_404(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(db_session)
        before = (await client.get(f"/endpoint-types/{type_id}")).json()

        cases = (
            ({"missing_ext": ["serial_number"]}, "Extension 'missing_ext' not found"),
            ({name: ["nope"]}, f"Extension '{name}' declares no endpoint field 'nope'"),
        )
        for extension_fields, message in cases:
            response = await client.patch(
                f"/endpoint-types/{type_id}",
                json={"label": _label(), "extension_fields": extension_fields},
            )
            assert response.status_code == 404, response.text
            assert response.json()["message"] == message
        await self._assert_unchanged(client, type_id, before)

    async def test_patch_unknown_type_with_extension_fields_is_type_404(self, client, db_session):
        enabled = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        disabled = await seed_extension(db_session, {"batch": STRING_FIELD}, enabled=False)
        missing_type = "00000000-0000-0000-0000-000000000000"

        for extension_fields in (
            {enabled: ["serial_number"]},
            {"missing_ext": ["serial_number"]},
            {disabled: ["batch"]},
        ):
            response = await client.patch(
                f"/endpoint-types/{missing_type}", json={"extension_fields": extension_fields}
            )
            assert response.status_code == 404, response.text
            assert response.json()["message"] == f"EndpointType '{missing_type}' not found"

    async def test_patch_role_on_managed_field_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        created = await client.post(
            "/endpoint-types",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert created.status_code == 201, created.text
        type_id = created.json()["type_id"]

        response = await client.patch(
            f"/endpoint-types/{type_id}", json={"mapping": {"serial_number": "name"}}
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == ROLE_MESSAGE.format(name)
        assert (await client.get(f"/endpoint-types/{type_id}")).json()["mapping"] == {}

    async def test_patch_role_on_added_extension_field_is_422(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(db_session)
        before = (await client.get(f"/endpoint-types/{type_id}")).json()

        response = await client.patch(
            f"/endpoint-types/{type_id}",
            json={
                "extension_fields": {name: ["serial_number"]},
                "mapping": {"serial_number": "name"},
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["message"] == ROLE_MESSAGE.format(name)
        await self._assert_unchanged(client, type_id, before)

    async def test_patch_only_extension_fields_works(self, client, db_session):
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(
            db_session, fields={"title": NOTE_FIELD}, mapping={"title": "name"}
        )

        response = await client.patch(
            f"/endpoint-types/{type_id}", json={"extension_fields": {name: ["serial_number"]}}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["fields"]) == {"title", "serial_number"}
        assert body["mapping"] == {"title": "name"}
        assert body["managed_by"] == {"serial_number": name}


PERM_OID = "managed-type-fields-perm-oid"


class TestExtensionFieldsOnTypesPermissions:
    @pytest.fixture
    def fake_jwt_user(self):
        return {
            "oid": PERM_OID,
            "sub": PERM_OID,
            "preferred_username": "managed-type-fields-perm@test.com",
            "name": "Managed Type Fields Perm",
            "roles": [],
        }

    async def _grant(self, db_session, *actions):
        await AbacFixtures(db_session).setup(
            users={"tester": PERM_OID},
            roles={"r": list(actions)},
            teams={"t": {"roles": ["r"], "users": ["tester"]}},
        )

    async def test_platform_config_write_can_create_and_patch(self, client, db_session):
        await self._grant(db_session, "platform.config.write")
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD, "batch": STRING_FIELD})

        created = await client.post(
            "/endpoint-types",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert created.status_code == 201, created.text

        patched = await client.patch(
            f"/endpoint-types/{created.json()['type_id']}",
            json={"extension_fields": {name: ["batch"]}},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["managed_by"] == {"serial_number": name, "batch": name}

    async def test_endpoint_write_cannot_create_or_patch(self, client, db_session):
        await self._grant(db_session, "device.endpoint.write")
        name = await seed_extension(db_session, {"serial_number": STRING_FIELD})
        type_id = await seed_endpoint_type(db_session)

        created = await client.post(
            "/endpoint-types",
            json={"label": _label(), "extension_fields": {name: ["serial_number"]}},
        )
        assert created.status_code == 403, created.text

        patched = await client.patch(
            f"/endpoint-types/{type_id}", json={"extension_fields": {name: ["serial_number"]}}
        )
        assert patched.status_code == 403, patched.text
        et = await _endpoint_repo(db_session).get_endpoint_type(type_id)
        assert et["managed_by"] == {}
