from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError

from legionctl.clients.sentinel_api import SentinelApiClient, build_api_url
from legionctl.errors import (
    AuthenticationError,
    CredentialError,
    MalformedResponseError,
    NodeConflictError,
    NodeUnreachableError,
    NodeValidationError,
    SentinelApiError,
    TlsError,
    UsageError,
)
from legionctl.models.profile import Profile
from legionctl.services.credentials import CredentialStore

SENTINEL_ID = "sentinel-north-door-01"
TOKEN = "super-secret-token"
BASE_URL = "https://sentinel-north-door-01.local"
API = f"{BASE_URL}/api/v1"

INFO: dict[str, Any] = {
    "api_version": "v1",
    "sentinel_id": SENTINEL_ID,
    "display_name": "North Door",
    "zone": "North Door",
    "firmware_version": "0.1.0",
    "build_id": "git-abcdef1",
    "capabilities": ["wifi_2_4ghz", "wifi_5ghz", "wifi_6", "ble", "bt_classic"],
    "profile_id": "event-alpha",
    "profile_revision": 4,
    "uptime_seconds": 81234,
}

HEALTH: dict[str, Any] = {
    "sentinel_id": SENTINEL_ID,
    "timestamp_utc": "2026-09-03T22:30:00Z",
    "battery": {"voltage_v": 3.92, "percent": 67, "charging": False},
    "wifi": {
        "connected": True,
        "ssid": "REDACTED_OR_OPTIONAL",
        "band": "5ghz",
        "rssi_dbm": -58,
        "ip": "192.168.50.41",
        "reconnect_count": 2,
    },
    "scanners": {"wifi": "running", "ble": "running", "bt_classic_coprocessor": "healthy"},
    "alert_queue": {"depth": 0, "last_delivery": "success"},
    "system": {"free_heap_bytes": 145280, "reset_reason": "power_on", "watchdog_resets": 0},
}

CONFIG: dict[str, Any] = {
    "sentinel_id": SENTINEL_ID,
    "zone": "North Door",
    "timezone": "America/New_York",
    "profile_id": "event-alpha",
    "profile_revision": 4,
    "discord_configured": True,
    "wifi_configured": True,
    "scan_policy": {
        "wifi_2_4_channels": [1, 6, 11],
        "wifi_5_channels": [36, 40, 44, 48],
        "wifi_dwell_ms": 250,
        "ble_scan_interval_ms": 100,
        "ble_scan_window_ms": 30,
        "classic_inquiry_seconds": 10,
        "classic_rest_seconds": 20,
    },
}

RULES: dict[str, Any] = {
    "profile_id": "event-alpha",
    "revision": 4,
    "schema_version": 1,
    "rules": [],
}

ACTIVATED: dict[str, Any] = {
    "status": "activated",
    "profile_id": "event-alpha",
    "revision": 4,
    "activation_timestamp_utc": "2026-09-03T22:31:00Z",
}

REJECTED: dict[str, Any] = {
    "status": "rejected",
    "errors": [
        {"path": "rules[0].minimum_rssi_dbm", "message": "must be between -100 and 0"}
    ],
}

TEST_ALERT: dict[str, Any] = {
    "accepted": True,
    "queued": False,
    "delivery": "success",
    "timestamp_utc": "2026-09-03T22:32:00Z",
}

EVENTS: dict[str, Any] = {
    "sentinel_id": SENTINEL_ID,
    "events": [
        {
            "event_id": "evt_01J7",
            "timestamp_utc": "2026-09-03T22:20:00Z",
            "event_type": "alert",
            "soi_id": "fox-03",
            "technology": "bt_classic",
            "rssi_dbm": -63,
            "confidence": {"hits": 3, "window_seconds": 15},
            "discord_delivery": "success",
        }
    ],
}

PROFILE_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "profile_id": "event-alpha",
    "revision": 4,
    "description": "test",
    "default_cooldown_seconds": 300,
    "scan_policy": {
        "wifi_2_4_channels": [1, 6, 11],
        "wifi_5_channels": [36, 40, 44, 48],
        "wifi_scan_interval_seconds": 15,
        "wifi_dwell_ms": 250,
        "ble_scan_interval_ms": 100,
        "ble_scan_window_ms": 30,
        "classic_inquiry_seconds": 10,
        "classic_rest_seconds": 20,
    },
    "rules": [
        {
            "id": "fox-03-classic",
            "name": "FOX-03 Bluetooth Classic",
            "enabled": True,
            "technology": "bt_classic",
            "match": {"all": [{"field": "address", "equals": "AA:BB:CC:DD:EE:FF"}]},
            "minimum_rssi_dbm": -78,
            "required_hits": 2,
            "window_seconds": 20,
            "cooldown_seconds": 300,
            "severity": "high",
        }
    ],
}


class MemoryStore:
    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self._tokens = dict(tokens or {})

    def set_token(self, sentinel_id: str, token: str) -> None:
        self._tokens[sentinel_id] = token

    def get_token(self, sentinel_id: str) -> str | None:
        return self._tokens.get(sentinel_id)

    def delete_token(self, sentinel_id: str) -> None:
        self._tokens.pop(sentinel_id, None)


def _credentials() -> CredentialStore:
    store = CredentialStore(store=MemoryStore())
    store.set_token(SENTINEL_ID, TOKEN)
    return store


def _client(**kwargs: Any) -> SentinelApiClient:
    return SentinelApiClient(
        BASE_URL,
        SENTINEL_ID,
        _credentials(),
        **kwargs,
    )


def _assert_no_secret(exc: BaseException) -> None:
    assert TOKEN not in str(exc)
    assert TOKEN not in repr(exc)


@pytest.mark.asyncio
async def test_typed_success_methods(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/info").mock(return_value=httpx.Response(200, json=INFO))
    respx_mock.get(f"{API}/health").mock(return_value=httpx.Response(200, json=HEALTH))
    respx_mock.get(f"{API}/config").mock(return_value=httpx.Response(200, json=CONFIG))
    respx_mock.get(f"{API}/rules").mock(return_value=httpx.Response(200, json=RULES))
    respx_mock.put(f"{API}/rules").mock(return_value=httpx.Response(200, json=ACTIVATED))
    respx_mock.post(f"{API}/commands/test-alert").mock(
        return_value=httpx.Response(200, json=TEST_ALERT)
    )
    respx_mock.post(f"{API}/commands/scan").mock(
        return_value=httpx.Response(200, json={"accepted": True, "action": "start"})
    )
    respx_mock.post(f"{API}/commands/reboot").mock(
        return_value=httpx.Response(200, json={"accepted": True})
    )
    respx_mock.get(f"{API}/events/recent").mock(return_value=httpx.Response(200, json=EVENTS))

    async with _client() as client:
        assert client.timeout.connect == 3.0
        assert client.timeout.read == 10.0
        assert client.timeout.write == 10.0
        assert client.tls_verify is True

        info = await client.get_info()
        assert info.sentinel_id == SENTINEL_ID
        assert info.profile_revision == 4

        health = await client.get_health()
        assert health.battery is not None
        assert health.battery.percent == 67

        config = await client.get_config()
        assert config.discord_configured is True
        assert config.scan_policy is not None

        rules = await client.get_rules()
        assert rules.revision == 4

        activated = await client.put_rules(Profile.model_validate(PROFILE_PAYLOAD))
        assert activated.status == "activated"

        alert = await client.test_alert()
        assert alert.delivery == "success"

        scan = await client.scan(action="start", technology="ble", duration_seconds=30)
        assert scan.accepted is True

        reboot = await client.reboot()
        assert reboot.accepted is True

        events = await client.recent_events(limit=50)
        assert events.events[0].event_type == "alert"
        assert events.events[0].soi_id == "fox-03"

    info_request = respx_mock.calls[0].request
    assert info_request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert info_request.headers["Accept"] == "application/json"

    put_request = next(call.request for call in respx_mock.calls if call.request.method == "PUT")
    assert "Idempotency-Key" in put_request.headers
    alert_request = next(
        call.request
        for call in respx_mock.calls
        if call.request.url.path.endswith("/commands/test-alert")
    )
    assert "Idempotency-Key" in alert_request.headers


@pytest.mark.asyncio
async def test_malformed_json(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/info").mock(
        return_value=httpx.Response(
            200,
            text="{not-json",
            headers={"Content-Type": "application/json"},
        )
    )
    async with _client() as client:
        with pytest.raises(MalformedResponseError, match="not valid JSON") as exc:
            await client.get_info()
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_invalid_response_schema(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/health").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )
    async with _client() as client:
        with pytest.raises(MalformedResponseError, match="schema validation") as exc:
            await client.get_health()
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_http_401(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{API}/info").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    async with _client() as client:
        with pytest.raises(AuthenticationError) as exc:
            await client.get_info()
    assert exc.value.exit_code == 3
    _assert_no_secret(exc.value)
    assert respx_mock.calls.call_count == 1


@pytest.mark.asyncio
async def test_http_409(respx_mock: respx.MockRouter) -> None:
    respx_mock.put(f"{API}/rules").mock(
        return_value=httpx.Response(409, json={"error": "conflict"})
    )
    async with _client() as client:
        with pytest.raises(NodeConflictError) as exc:
            await client.put_rules(Profile.model_validate(PROFILE_PAYLOAD))
    _assert_no_secret(exc.value)
    assert respx_mock.calls.call_count == 1


@pytest.mark.asyncio
async def test_http_422_profile_rejection(respx_mock: respx.MockRouter) -> None:
    respx_mock.put(f"{API}/rules").mock(return_value=httpx.Response(422, json=REJECTED))
    async with _client() as client:
        with pytest.raises(NodeValidationError) as exc:
            await client.put_rules(Profile.model_validate(PROFILE_PAYLOAD))
    assert "minimum_rssi_dbm" in str(exc.value)
    assert exc.value.errors
    _assert_no_secret(exc.value)
    assert respx_mock.calls.call_count == 1


@pytest.mark.asyncio
async def test_timeout(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/info").mock(side_effect=httpx.ReadTimeout("read timeout"))
    async with _client() as client:
        with pytest.raises(NodeUnreachableError, match="timed out") as exc:
            await client.get_info()
    assert exc.value.exit_code == 2
    assert route.call_count == 3
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_unreachable_node(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/info").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    async with _client() as client:
        with pytest.raises(NodeUnreachableError, match="unreachable") as exc:
            await client.get_info()
    assert route.call_count == 3
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_tls_error_mapping(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/info").mock(
        side_effect=httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")
    )
    async with _client() as client:
        with pytest.raises(TlsError, match="TLS") as exc:
            await client.get_info()
    assert exc.value.exit_code == 3
    assert route.call_count == 1
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_authentication_error_from_missing_token() -> None:
    credentials = CredentialStore(store=MemoryStore())
    async with SentinelApiClient(BASE_URL, SENTINEL_ID, credentials) as client:
        with pytest.raises(CredentialError) as exc:
            await client.get_info()
    assert exc.value.exit_code == 3
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_no_retry_for_side_effecting_writes(respx_mock: respx.MockRouter) -> None:
    timeout = httpx.ReadTimeout("read timeout")
    alert_route = respx_mock.post(f"{API}/commands/test-alert").mock(side_effect=timeout)
    scan_route = respx_mock.post(f"{API}/commands/scan").mock(side_effect=timeout)
    reboot_route = respx_mock.post(f"{API}/commands/reboot").mock(side_effect=timeout)
    put_route = respx_mock.put(f"{API}/rules").mock(side_effect=timeout)
    profile = Profile.model_validate(PROFILE_PAYLOAD)

    async with _client() as client:
        with pytest.raises(NodeUnreachableError):
            await client.test_alert()
        with pytest.raises(NodeUnreachableError):
            await client.scan(action="start", technology="ble", duration_seconds=30)
        with pytest.raises(NodeUnreachableError):
            await client.reboot()
        with pytest.raises(NodeUnreachableError):
            await client.put_rules(profile)

    assert alert_route.call_count == 1
    assert scan_route.call_count == 1
    assert reboot_route.call_count == 1
    assert put_route.call_count == 1


@pytest.mark.asyncio
async def test_no_retry_for_write_http_500(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{API}/commands/test-alert").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    async with _client() as client:
        with pytest.raises(SentinelApiError) as exc:
            await client.test_alert()
    assert route.call_count == 1
    _assert_no_secret(exc.value)


@pytest.mark.asyncio
async def test_read_retries_then_success(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{API}/info").mock(
        side_effect=[
            httpx.ReadTimeout("read timeout"),
            httpx.ReadTimeout("read timeout"),
            httpx.Response(200, json=INFO),
        ]
    )
    async with _client() as client:
        info = await client.get_info()
    assert info.sentinel_id == SENTINEL_ID
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_scan_duration_rejected() -> None:
    async with _client() as client:
        with pytest.raises(UsageError, match="scan duration"):
            await client.scan(action="start", technology="ble", duration_seconds=301)


def test_build_api_url() -> None:
    assert build_api_url(BASE_URL, "info") == f"{API}/info"
    assert build_api_url(f"{API}", "health") == f"{API}/health"
    assert build_api_url(f"{API}/", "commands/scan") == f"{API}/commands/scan"


def test_tls_verify_default() -> None:
    client = _client()
    assert client.tls_verify is True
    insecure = _client(insecure_skip_tls_verify=True)
    assert insecure.tls_verify is False


def test_profile_fixture_is_valid() -> None:
    Profile.model_validate(PROFILE_PAYLOAD)


def test_invalid_health_model_still_fail_closed() -> None:
    with pytest.raises(ValidationError):
        from legionctl.models.node_api import HealthResponse

        HealthResponse.model_validate({"sentinel_id": SENTINEL_ID})
