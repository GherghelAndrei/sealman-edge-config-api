"""Network overview: suggestions only, live state (spec §2)."""
from uuid import uuid4

from sqlalchemy import select

from db.models.host_status import DeviceHostStatus, DevicePortStatus
from db.registry import repo_registry
from db.repos.host_status import HostStatusRepository
from tests.integration.test_abac_authorization import AbacFixtures

DEVICE = "overview-dev"
STRING_FIELD = {"type": "string", "label": "Text"}
INT_FIELD = {"type": "integer", "label": "Port"}


def _label() -> str:
    return f"nw-{uuid4().hex[:8]}"


def _host(ip, ports=None, status="online"):
    return {
        "ip": ip,
        "status": status,
        "ports": {str(port): {"status": port_status} for port, port_status in (ports or {}).items()},
    }


def _scan(hosts, ports, network="10.20.0.0", mask=24):
    return {
        "scanResults": hosts,
        "scanDefinition": {"networkDefinition": network, "subnetMask": mask, "ports": ports},
    }


async def _endpoint_type(client, fields, mapping) -> str:
    response = await client.post(
        "/endpoint-types", json={"label": _label(), "fields": fields, "mapping": mapping}
    )
    assert response.status_code == 201, response.text
    return response.json()["type_id"]


async def _service_type(client, fields, mapping) -> str:
    response = await client.post(
        "/service-types", json={"label": _label(), "fields": fields, "mapping": mapping}
    )
    assert response.status_code == 201, response.text
    return response.json()["type_id"]


async def _endpoint(client, type_id, data) -> str:
    response = await client.post(
        f"/endpoints?device_id={DEVICE}", json={"type_id": type_id, "endpoint_data": data}
    )
    assert response.status_code == 201, response.text
    return response.json()["endpoint_id"]


async def _service(client, endpoint_id, type_id, data) -> str:
    response = await client.post(
        f"/services?endpoint_id={endpoint_id}", json={"type_id": type_id, "service_data": data}
    )
    assert response.status_code == 201, response.text
    return response.json()["service_id"]


async def _overview(client, body):
    response = await client.post(f"/{DEVICE}/network/overview", json=body)
    assert response.status_code == 200, response.text
    return response.json()["endpoints"]


def _by_ip(entries, ip):
    return next(entry for entry in entries if entry.get("ip") == ip)


class TestOverviewSuggestsOnly:
    async def test_default_ip_match_is_suggested_and_not_created(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        type_id = await _endpoint_type(
            client, {"addr": {**STRING_FIELD, "default": "10.20.0.5"}}, {"addr": "ip"}
        )

        entries = await _overview(client, _scan([_host("10.20.0.5")], []))

        entry = _by_ip(entries, "10.20.0.5")
        assert entry["source"] == "default"
        assert entry["type_id"] == type_id
        assert "endpoint_id" not in entry
        assert (await client.get(f"/endpoints?device_id={DEVICE}")).json() == []

    async def test_default_port_match_is_suggested_and_not_created(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"addr": STRING_FIELD}, {"addr": "ip"})
        service_type = await _service_type(
            client, {"p": {**INT_FIELD, "default": 47001}}, {"p": "port"}
        )
        endpoint_id = await _endpoint(client, endpoint_type, {"addr": "10.20.0.11"})

        entries = await _overview(
            client, _scan([_host("10.20.0.11", {47001: "online"})], [47001])
        )

        port = next(p for p in _by_ip(entries, "10.20.0.11")["ports"] if p.get("port") == 47001)
        assert port["source"] == "default"
        assert port["type_id"] == service_type
        assert "service_id" not in port
        assert (await client.get(f"/services?endpoint_id={endpoint_id}")).json() == []

    async def test_host_and_port_status_history_still_written(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        await _endpoint_type(
            client, {"addr": {**STRING_FIELD, "default": "10.20.0.6"}}, {"addr": "ip"}
        )
        await _service_type(client, {"p": {**INT_FIELD, "default": 47003}}, {"p": "port"})

        await _overview(client, _scan([_host("10.20.0.6", {47003: "online"})], [47003]))

        hosts = (await db_session.execute(
            select(DeviceHostStatus).where(DeviceHostStatus.device_id == DEVICE)
        )).scalars().all()
        ports = (await db_session.execute(
            select(DevicePortStatus).where(DevicePortStatus.device_id == DEVICE)
        )).scalars().all()
        assert [(h.ip, h.status) for h in hosts] == [("10.20.0.6", "online")]
        assert [(p.ip, p.port, p.status) for p in ports] == [("10.20.0.6", 47003, "online")]
        assert (await client.get(f"/endpoints?device_id={DEVICE}")).json() == []


class TestOverviewLiveStateUnchanged:
    # Regression guards: these pass before and after this task.
    async def test_configured_endpoint_and_service_get_live_status(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"addr": STRING_FIELD}, {"addr": "ip"})
        service_type = await _service_type(client, {"p": INT_FIELD}, {"p": "port"})
        endpoint_id = await _endpoint(client, endpoint_type, {"addr": "10.20.0.12"})
        service_id = await _service(client, endpoint_id, service_type, {"p": 47002})

        entries = await _overview(
            client, _scan([_host("10.20.0.12", {47002: "online"})], [47002])
        )

        entry = _by_ip(entries, "10.20.0.12")
        assert entry["source"] == "configured"
        assert entry["endpoint_id"] == endpoint_id
        assert entry["status"] == "online"
        port = next(p for p in entry["ports"] if p.get("port") == 47002)
        assert port["service_id"] == service_id
        assert port["status"] == "online"

    async def test_configured_endpoint_missing_from_scan_in_range_is_offline(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"addr": STRING_FIELD}, {"addr": "ip"})
        await _endpoint(client, endpoint_type, {"addr": "10.20.0.13"})

        entries = await _overview(client, _scan([], []))

        assert _by_ip(entries, "10.20.0.13")["status"] == "offline"


class TestOverviewWithoutAddress:
    async def _ipless_endpoint(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"serial": STRING_FIELD}, {})
        return await _endpoint(client, endpoint_type, {"serial": "SN-1"})

    async def test_endpoint_without_ip_is_listed_unknown(self, client, db_session):
        endpoint_id = await self._ipless_endpoint(client, db_session)

        entries = await _overview(client, _scan([], []))

        entry = next(e for e in entries if e.get("endpoint_id") == endpoint_id)
        assert entry["status"] == "unknown"
        assert entry["source"] == "configured"
        assert "ip" not in entry
        assert "lastStatusChange" not in entry

    async def test_services_of_endpoint_without_ip_are_listed_unknown(self, client, db_session):
        endpoint_id = await self._ipless_endpoint(client, db_session)
        with_port = await _service_type(client, {"p": INT_FIELD}, {"p": "port"})
        without_port = await _service_type(client, {"protocol": STRING_FIELD}, {})
        port_service = await _service(client, endpoint_id, with_port, {"p": 47201})
        portless_service = await _service(client, endpoint_id, without_port, {"protocol": "modbus"})

        entries = await _overview(client, _scan([], []))

        ports = {p["service_id"]: p for p in next(e for e in entries if e.get("endpoint_id") == endpoint_id)["ports"]}
        assert ports[port_service]["status"] == "unknown"      # Q13
        assert ports[port_service]["port"] == 47201
        assert ports[portless_service]["status"] == "unknown"
        assert "port" not in ports[portless_service]

    async def test_endpoint_with_empty_ip_value_is_listed_unknown(self, client, db_session):
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"addr": STRING_FIELD}, {"addr": "ip"})
        endpoint_id = await _endpoint(client, endpoint_type, {"addr": ""})

        entries = await _overview(client, _scan([], []))

        entry = next(e for e in entries if e.get("endpoint_id") == endpoint_id)
        assert entry["status"] == "unknown"
        statuses = await repo_registry.get(HostStatusRepository)(db_session).get_host_statuses(DEVICE)
        assert "" not in statuses

    async def test_service_without_port_on_endpoint_with_ip_is_listed_unknown(self, client, db_session):
        # Q2 (resolved): applies to endpoints with an IP too.
        await AbacFixtures(db_session).setup(devices={DEVICE: {}})
        endpoint_type = await _endpoint_type(client, {"addr": STRING_FIELD}, {"addr": "ip"})
        without_port = await _service_type(client, {"protocol": STRING_FIELD}, {})
        endpoint_id = await _endpoint(client, endpoint_type, {"addr": "10.20.0.30"})
        service_id = await _service(client, endpoint_id, without_port, {"protocol": "modbus"})

        live = await _overview(client, _scan([_host("10.20.0.30")], []))
        live_port = next(p for p in _by_ip(live, "10.20.0.30")["ports"] if p.get("service_id") == service_id)
        assert live_port["status"] == "unknown"
        assert "port" not in live_port

        last_known = (await client.get(f"/{DEVICE}/network/last-known")).json()["endpoints"]
        known_port = next(p for p in _by_ip(last_known, "10.20.0.30")["ports"] if p.get("service_id") == service_id)
        assert known_port["status"] == "unknown"

    async def test_last_known_overview_includes_endpoint_without_ip(self, client, db_session):
        endpoint_id = await self._ipless_endpoint(client, db_session)

        response = await client.get(f"/{DEVICE}/network/last-known")

        assert response.status_code == 200, response.text
        entry = next(e for e in response.json()["endpoints"] if e.get("endpoint_id") == endpoint_id)
        assert entry["status"] == "unknown"
        assert "ip" not in entry
