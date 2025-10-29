from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

import custom_components.tronbytassistant.__init__ as tronbyt_init
from custom_components.tronbytassistant.__init__ import TronbytCoordinator


class MockResponse:
    """Lightweight aiohttp response stand-in."""

    def __init__(self, status: int, payload: dict[str, Any] | None = None):
        self.status = status
        self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def text(self) -> str:
        return json.dumps(self._payload)


class MockRequestContext:
    """Async context manager for the mocked responses."""

    def __init__(self, response: MockResponse):
        self._response = response

    async def __aenter__(self) -> MockResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class MockSession:
    """Minimal aiohttp-like session for tests."""

    def __init__(self) -> None:
        self._queue: dict[str, list[MockResponse]] = {"get": [], "patch": []}
        self.get_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.patch_calls: list[
            tuple[str, dict[str, Any] | None, dict[str, Any] | None]
        ] = []

    def queue_response(self, method: str, response: MockResponse) -> None:
        self._queue[method].append(response)

    def get(
        self, url: str, headers: dict[str, Any] | None = None
    ) -> MockRequestContext:
        self.get_calls.append((url, headers))
        if not self._queue["get"]:
            raise AssertionError(f"Unexpected GET: {url}")
        return MockRequestContext(self._queue["get"].pop(0))

    def patch(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> MockRequestContext:
        self.patch_calls.append((url, headers, json))
        if not self._queue["patch"]:
            raise AssertionError(f"Unexpected PATCH: {url}")
        return MockRequestContext(self._queue["patch"].pop(0))


def _coordinator(hass: HomeAssistant) -> TronbytCoordinator:
    return TronbytCoordinator(hass, "https://api.example", "token", True)


@pytest.mark.asyncio
async def test_coordinator_fetches_devices_with_installations(hass: HomeAssistant):
    """Coordinator should normalize device payloads and append installations."""
    session = MockSession()
    session.queue_response(
        "get",
        MockResponse(
            200,
            {
                "devices": [
                    {
                        "id": "dev1",
                        "displayName": "Living Room",
                        "type": "Model X",
                        "notes": "Upstairs",
                        "intervalSec": 120,
                        "brightness": 80,
                        "nightMode": {
                            "enabled": True,
                            "app": "123",
                            "startTime": "21:00",
                            "endTime": "06:00",
                            "brightness": 20,
                        },
                        "dimMode": {"startTime": "07:00", "brightness": 10},
                        "pinnedApp": "123",
                    }
                ]
            },
        ),
    )

    coordinator = _coordinator(hass)
    coordinator._async_fetch_installations = AsyncMock(
        return_value=[{"id": "inst1", "enabled": True}]
    )

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        data = await coordinator._async_update_data()

    assert len(data) == 1
    device = data[0]
    assert device["name"] == "Living Room"
    assert device["interval"] == 120
    assert device["night_mode"]["app"] == "123"
    assert device["installations"] == [{"id": "inst1", "enabled": True}]
    coordinator._async_fetch_installations.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_raises_when_no_devices(hass: HomeAssistant):
    """The coordinator raises UpdateFailed when no devices are returned."""
    session = MockSession()
    session.queue_response("get", MockResponse(200, {"devices": []}))

    coordinator = _coordinator(hass)
    coordinator._async_fetch_installations = AsyncMock()

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_http_failure_is_wrapped(hass: HomeAssistant):
    """Unexpected HTTP codes should surface as UpdateFailed."""
    session = MockSession()
    session.queue_response("get", MockResponse(500, {"error": "boom"}))

    coordinator = _coordinator(hass)
    coordinator._async_fetch_installations = AsyncMock()

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_fetch_installations(hass: HomeAssistant):
    """Validate _async_fetch_installations success and error handling."""
    session = MockSession()
    session.queue_response(
        "get",
        MockResponse(
            200,
            {
                "installations": [
                    {"id": "123", "enabled": True},
                    {"id": "456", "enabled": False},
                ]
            },
        ),
    )

    coordinator = _coordinator(hass)
    result = await coordinator._async_fetch_installations(session, "dev1")
    assert len(result) == 2

    session_error = MockSession()
    session_error.queue_response("get", MockResponse(500, {"error": "bad"}))
    with pytest.raises(UpdateFailed):
        await coordinator._async_fetch_installations(session_error, "dev1")


@pytest.mark.asyncio
async def test_async_patch_device_updates_local_state(hass: HomeAssistant):
    """Patch responses should be merged immediately into coordinator data."""
    session = MockSession()
    session.queue_response(
        "patch",
        MockResponse(
            200,
            {
                "id": "dev1",
                "displayName": "Living Room",
                "type": "Model X",
                "notes": "Updated note",
                "intervalSec": 60,
                "brightness": 90,
                "nightMode": {"enabled": True, "app": "999", "startTime": "20:00"},
                "dimMode": {"startTime": "07:00", "brightness": 12},
                "pinnedApp": "999",
            },
        ),
    )
    session.queue_response(
        "get",
        MockResponse(
            200, {"installations": [{"id": "inst1", "enabled": False, "appID": "App"}]}
        ),
    )

    coordinator = _coordinator(hass)
    coordinator.data = [
        {
            "id": "dev1",
            "name": "Living Room",
            "type": "Model X",
            "notes": "Old",
            "interval": 120,
            "brightness": 80,
            "night_mode": {"enabled": False, "app": "123"},
            "dim_mode": {"start": None, "brightness": None},
            "pinned_app": "123",
            "auto_dim": False,
            "installations": [],
        }
    ]
    coordinator.async_set_updated_data = MagicMock()

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        await coordinator.async_patch_device("dev1", {"brightness": 90})

    assert session.patch_calls[0][0].endswith("/v0/devices/dev1")
    assert coordinator.data[0]["brightness"] == 90
    assert coordinator.data[0]["night_mode"]["app"] == "999"
    assert coordinator.data[0]["installations"][0]["id"] == "inst1"
    coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)


@pytest.mark.asyncio
async def test_async_patch_installation_updates_local_state(hass: HomeAssistant):
    """Installation PATCH should update coordinator cache without a refetch."""
    session = MockSession()
    session.queue_response(
        "patch",
        MockResponse(
            200,
            {
                "id": "inst1",
                "appID": "App",
                "enabled": True,
                "pinned": False,
            },
        ),
    )

    coordinator = _coordinator(hass)
    coordinator.data = [
        {
            "id": "dev1",
            "name": "Living Room",
            "type": "Model X",
            "notes": "",
            "interval": 120,
            "brightness": 80,
            "night_mode": {"enabled": True, "app": "123"},
            "dim_mode": {"start": None, "brightness": None},
            "pinned_app": None,
            "auto_dim": False,
            "installations": [{"id": "inst1", "enabled": False, "appID": "App"}],
        }
    ]
    coordinator.async_set_updated_data = MagicMock()

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        await coordinator.async_patch_installation(
            "dev1", "inst1", {"set_enabled": True}
        )

    assert session.patch_calls[0][0].endswith("/v0/devices/dev1/installations/inst1")
    assert coordinator.data[0]["installations"][0]["enabled"] is True
    coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)


def test_merge_helpers_skip_when_device_missing(hass: HomeAssistant):
    """Ensure merge helpers safely no-op when the target device is absent."""
    coordinator = _coordinator(hass)
    coordinator.data = None
    coordinator._merge_device_update("dev1", {}, [])
    coordinator._merge_installation_update("dev1", {})

    coordinator.data = []
    coordinator._merge_device_update("dev1", {}, [])
    coordinator._merge_installation_update("dev1", {})


def test_merge_device_update_overwrites_fields(hass: HomeAssistant):
    """Verify merge logic replaces device properties using payload data."""
    coordinator = _coordinator(hass)
    coordinator.data = [
        {
            "id": "dev1",
            "name": "Living Room",
            "type": "Model X",
            "notes": "Old",
            "interval": 30,
            "brightness": 50,
            "night_mode": {"enabled": False},
            "dim_mode": {"start": None, "brightness": None},
            "pinned_app": None,
            "auto_dim": False,
            "installations": [],
        }
    ]

    coordinator._merge_device_update(
        "dev1",
        {
            "id": "dev1",
            "displayName": "Living Room",
            "type": "Model X2",
            "notes": "New note",
            "intervalSec": 120,
            "brightness": 90,
            "nightMode": {"enabled": True, "app": "abc"},
            "dimMode": {"startTime": "20:00", "brightness": 5},
            "pinnedApp": "abc",
        },
        [{"id": "inst1"}],
    )

    updated = coordinator.data[0]
    assert updated["interval"] == 120
    assert updated["night_mode"]["app"] == "abc"
    assert updated["dim_mode"]["start"] == "20:00"
    assert updated["installations"] == [{"id": "inst1"}]


def test_merge_installation_update_adds_new(hass: HomeAssistant):
    """When an installation is missing it should be appended."""
    coordinator = _coordinator(hass)
    coordinator.data = [
        {
            "id": "dev1",
            "installations": [{"id": "existing", "enabled": False}],
        }
    ]

    coordinator._merge_installation_update(
        "dev1",
        {"id": "new", "enabled": True},
    )

    installs = coordinator.data[0]["installations"]
    assert len(installs) == 2
    assert installs[1]["id"] == "new"


@pytest.mark.asyncio
async def test_async_patch_device_error_propagates(hass: HomeAssistant):
    """Non-200 responses should raise HomeAssistantError."""
    session = MockSession()
    session.queue_response("patch", MockResponse(400, {"error": "bad"}))

    coordinator = _coordinator(hass)
    coordinator.data = [{"id": "dev1"}]

    with patch.object(tronbyt_init, "async_get_clientsession", return_value=session):
        with pytest.raises(HomeAssistantError):
            await coordinator.async_patch_device("dev1", {"brightness": 90})
