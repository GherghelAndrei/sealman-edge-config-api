"""An extension manifest's `endpoint_fields` section: validation, storage and GET output."""
from tests.integration.extension_fixtures import STRING_FIELD, manifest, unique_extension_name


async def _register(client, name, endpoint_fields=None):
    return await client.post("/extensions", json=manifest(name, endpoint_fields))


class TestManifestEndpointFields:
    async def test_register_stores_and_returns_fields(self, client):
        name = unique_extension_name()
        created = await _register(client, name, {"serial_number": STRING_FIELD})
        assert created.status_code == 201, created.text
        assert created.json()["endpoint_fields"]["serial_number"]["label"] == "Serial number"

        detail = await client.get(f"/extensions/{name}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["endpoint_fields"]["serial_number"]["label"] == "Serial number"
        assert detail.json()["endpoint_fields"]["serial_number"]["ui"] == "input"

        listing = await client.get("/extensions")
        assert listing.status_code == 200, listing.text
        item = next(ext for ext in listing.json() if ext["name"] == name)
        assert item["endpoint_fields"]["serial_number"]["label"] == "Serial number"

    async def test_register_without_section_returns_empty_object(self, client):
        name = unique_extension_name()
        created = await _register(client, name)
        assert created.status_code == 201, created.text
        assert created.json()["endpoint_fields"] == {}

        detail = await client.get(f"/extensions/{name}")
        assert detail.json()["endpoint_fields"] == {}

    async def test_register_required_true_is_422_and_not_persisted(self, client):
        name = unique_extension_name()
        response = await _register(client, name, {"serial_number": {**STRING_FIELD, "required": True}})
        assert response.status_code == 422, response.text
        assert "Endpoint field 'serial_number' cannot be required" in response.text

        assert (await client.get(f"/extensions/{name}")).status_code == 404

    async def test_register_invalid_definition_is_422(self, client):
        name = unique_extension_name()
        response = await _register(client, name, {"serial_number": {"type": "string"}})
        assert response.status_code == 422, response.text
        assert "Invalid endpoint field 'serial_number'" in response.text

        assert (await client.get(f"/extensions/{name}")).status_code == 404

    async def test_register_non_object_definition_is_422(self, client):
        name = unique_extension_name()
        response = await _register(client, name, {"serial_number": "string"})
        assert response.status_code == 422, response.text
        assert "Invalid endpoint field 'serial_number'" in response.text

        assert (await client.get(f"/extensions/{name}")).status_code == 404

    async def test_put_without_section_keeps_stored_fields(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        replaced = await client.put(f"/extensions/{name}", json=manifest(name))
        assert replaced.status_code == 200, replaced.text
        assert list(replaced.json()["endpoint_fields"]) == ["serial_number"]

        detail = await client.get(f"/extensions/{name}")
        assert list(detail.json()["endpoint_fields"]) == ["serial_number"]

    async def test_put_null_section_keeps_stored_fields(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        body = {**manifest(name), "endpoint_fields": None}
        replaced = await client.put(f"/extensions/{name}", json=body)
        assert replaced.status_code == 200, replaced.text
        assert list(replaced.json()["endpoint_fields"]) == ["serial_number"]

    async def test_put_empty_object_clears_fields(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        replaced = await client.put(f"/extensions/{name}", json=manifest(name, {}))
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["endpoint_fields"] == {}

        detail = await client.get(f"/extensions/{name}")
        assert detail.json()["endpoint_fields"] == {}

    async def test_put_replaces_fields(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        replaced = await client.put(f"/extensions/{name}", json=manifest(name, {"asset_tag": STRING_FIELD}))
        assert replaced.status_code == 200, replaced.text
        assert list(replaced.json()["endpoint_fields"]) == ["asset_tag"]

        detail = await client.get(f"/extensions/{name}")
        assert list(detail.json()["endpoint_fields"]) == ["asset_tag"]

    async def test_put_invalid_definition_is_422_and_keeps_stored_fields(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        body = manifest(name, {"asset_tag": {**STRING_FIELD, "required": True}})
        replaced = await client.put(f"/extensions/{name}", json=body)
        assert replaced.status_code == 422, replaced.text

        detail = await client.get(f"/extensions/{name}")
        assert list(detail.json()["endpoint_fields"]) == ["serial_number"]

    async def test_schema_lists_endpoint_fields(self, client):
        response = await client.get("/extensions/schema")
        assert response.status_code == 200, response.text
        assert "endpoint_fields" in response.text


class TestEndpointFieldOwnership:
    async def test_register_key_owned_by_other_is_409(self, client):
        owner = unique_extension_name()
        other = unique_extension_name()
        assert (await _register(client, owner, {"serial_number": STRING_FIELD})).status_code == 201

        response = await _register(client, other, {"serial_number": STRING_FIELD})
        assert response.status_code == 409, response.text
        assert f"Endpoint field 'serial_number' is already declared by extension '{owner}'" in response.text

        assert (await client.get(f"/extensions/{other}")).status_code == 404

    async def test_put_key_owned_by_other_is_409(self, client):
        owner = unique_extension_name()
        other = unique_extension_name()
        assert (await _register(client, owner, {"serial_number": STRING_FIELD})).status_code == 201
        assert (await _register(client, other, {"asset_tag": STRING_FIELD})).status_code == 201

        body = manifest(other, {"asset_tag": STRING_FIELD, "serial_number": STRING_FIELD})
        response = await client.put(f"/extensions/{other}", json=body)
        assert response.status_code == 409, response.text
        assert f"Endpoint field 'serial_number' is already declared by extension '{owner}'" in response.text

        detail = await client.get(f"/extensions/{other}")
        assert list(detail.json()["endpoint_fields"]) == ["asset_tag"]

    async def test_put_own_keys_is_not_a_conflict(self, client):
        name = unique_extension_name()
        assert (await _register(client, name, {"serial_number": STRING_FIELD})).status_code == 201

        response = await client.put(f"/extensions/{name}", json=manifest(name, {"serial_number": STRING_FIELD}))
        assert response.status_code == 200, response.text

    async def test_key_free_again_after_owner_drops_it(self, client):
        owner = unique_extension_name()
        other = unique_extension_name()
        assert (await _register(client, owner, {"serial_number": STRING_FIELD})).status_code == 201
        assert (await client.put(f"/extensions/{owner}", json=manifest(owner, {}))).status_code == 200

        response = await _register(client, other, {"serial_number": STRING_FIELD})
        assert response.status_code == 201, response.text
