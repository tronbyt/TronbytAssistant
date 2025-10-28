from __future__ import annotations

from copy import deepcopy
from datetime import time as time_obj
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from custom_components.tronbytassistant.const import DOMAIN
from custom_components.tronbytassistant import light as light_mod
from custom_components.tronbytassistant import number as number_mod
from custom_components.tronbytassistant import select as select_mod
from custom_components.tronbytassistant import switch as switch_mod
from custom_components.tronbytassistant import time as time_mod
from custom_components.tronbytassistant.__init__ import TronbytCoordinator


@pytest.fixture
def device_payload() -> dict[str, Any]:
    """Return a canonical device payload used across entity tests."""
    return {
        "id": "dev1",
        "name": "Living Room",
        "type": "Model X",
        "notes": "Second floor",
        "interval": 90,
        "brightness": 80,
        "night_mode": {
            "enabled": True,
            "app": "477",
            "start": "21:00",
            "end": "06:15",
            "brightness": 25,
        },
        "dim_mode": {"start": "10:00", "brightness": 30},
        "pinned_app": "217",
        "auto_dim": False,
        "installations": [
            {"id": "477", "appID": "Custom Clock", "enabled": True},
            {"id": "217", "appID": "Weather", "enabled": False},
            {"id": "999", "appID": None, "enabled": True},
        ],
    }


@pytest.fixture
def coordinator(hass, device_payload: dict[str, Any]) -> TronbytCoordinator:
    """Coordinator instance with seeded device data."""
    coordinator = TronbytCoordinator(hass, "https://api.example", "token")
    coordinator.data = [deepcopy(device_payload)]
    return coordinator


def test_value_from_device():
    """Ensure the helper safely drills into nested structures."""
    device = {"a": {"b": {"c": 5}}}
    assert light_mod._value_from_device(device, ["a", "b", "c"]) == 5
    assert light_mod._value_from_device(device, ["a", "missing"]) is None
    assert light_mod._value_from_device(device, ["a", "b", "c", "d"]) is None


@pytest.mark.asyncio
async def test_light_brightness_and_controls(coordinator: TronbytCoordinator):
    """Verify brightness math and PATCH payloads."""
    entity = light_mod.TronbytLight(
        coordinator, "dev1", light_mod.LIGHT_DESCRIPTIONS[0]
    )
    coordinator.async_patch_device = AsyncMock()

    assert entity.unique_id == "tronbyt-brightness-dev1"
    # 80% brightness -> 204 (rounded)
    assert entity.brightness == 204
    assert entity.is_on is True

    await entity.async_turn_on(brightness=64)
    coordinator.async_patch_device.assert_awaited_once_with("dev1", {"brightness": 25})

    coordinator.async_patch_device.reset_mock()
    await entity.async_turn_off()
    coordinator.async_patch_device.assert_awaited_once_with("dev1", {"brightness": 0})


@pytest.mark.asyncio
async def test_night_mode_brightness_defaults(coordinator: TronbytCoordinator):
    """Night mode light should use the default on value if brightness unavailable."""
    data = deepcopy(coordinator.data[0])
    data["night_mode"]["brightness"] = None
    coordinator.data = [data]

    entity = light_mod.TronbytLight(
        coordinator, "dev1", light_mod.LIGHT_DESCRIPTIONS[1]
    )
    coordinator.async_patch_device = AsyncMock()

    assert entity.brightness is None
    await entity.async_turn_on()
    coordinator.async_patch_device.assert_awaited_once_with(
        "dev1", {"nightModeBrightness": 50}
    )


def test_number_native_value_and_device_info(coordinator: TronbytCoordinator):
    """Validate number entity properties."""
    entity = number_mod.TronbytNumber(
        coordinator, "dev1", number_mod.NUMBER_DESCRIPTIONS[0]
    )
    assert entity.native_value == 90
    info = entity.device_info
    assert info["identifiers"] == {(DOMAIN, "dev1")}
    assert info["model"] == "Model X"


@pytest.mark.asyncio
async def test_number_clamps_patch_payload(coordinator: TronbytCoordinator):
    """Ensure values are clamped to coordinator constraints before PATCH."""
    entity = number_mod.TronbytNumber(
        coordinator, "dev1", number_mod.NUMBER_DESCRIPTIONS[0]
    )
    coordinator.async_patch_device = AsyncMock()
    await entity.async_set_native_value(-5)
    coordinator.async_patch_device.assert_awaited_once_with("dev1", {"intervalSec": 1})


def test_time_entity_native_value_and_device_info(coordinator: TronbytCoordinator):
    """Verify time parsing with HH:MM inputs."""
    entity = time_mod.TronbytTime(coordinator, "dev1", time_mod.TIME_DESCRIPTIONS[0])

    assert entity.native_value == time_obj(21, 0, 0)
    info = entity.device_info
    assert info["name"] == "Living Room"


@pytest.mark.asyncio
async def test_time_entity_set_value_formats_payload(coordinator: TronbytCoordinator):
    """Ensure time updates send HH:MM payloads and support clearing values."""
    entity = time_mod.TronbytTime(coordinator, "dev1", time_mod.TIME_DESCRIPTIONS[2])
    coordinator.async_patch_device = AsyncMock()

    await entity.async_set_value(time_obj(7, 45))
    coordinator.async_patch_device.assert_awaited_once_with(
        "dev1", {"dimModeStartTime": "07:45"}
    )

    coordinator.async_patch_device.reset_mock()
    await entity.async_set_value(None)
    coordinator.async_patch_device.assert_awaited_once_with(
        "dev1", {"dimModeStartTime": ""}
    )


def test_select_options_and_current_option(coordinator: TronbytCoordinator):
    """Select options should include human readable labels with IDs."""
    entity = select_mod.TronbytSelect(
        coordinator, "dev1", select_mod.SELECT_DESCRIPTIONS[0]
    )
    options = entity.options
    assert options[0] == "None"
    assert "Custom Clock-477" in options
    assert "999" in options
    assert entity.current_option == "Custom Clock-477"


@pytest.mark.asyncio
async def test_select_option_updates_device(coordinator: TronbytCoordinator):
    """Selecting a new option sends the de-suffixed installation id."""
    entity = select_mod.TronbytSelect(
        coordinator, "dev1", select_mod.SELECT_DESCRIPTIONS[1]
    )
    coordinator.async_patch_device = AsyncMock()

    await entity.async_select_option("Weather-217")
    coordinator.async_patch_device.assert_awaited_once_with(
        "dev1", {"pinnedApp": "217"}
    )

    coordinator.async_patch_device.reset_mock()
    await entity.async_select_option("None")
    coordinator.async_patch_device.assert_awaited_once_with("dev1", {"pinnedApp": ""})


def test_select_normalize_value():
    """Ensure select normalization collapses blank values to None."""
    normalize = select_mod.TronbytSelect._normalize_value
    assert normalize(None) is None
    assert normalize("  ") is None
    assert normalize("None") is None
    assert normalize("Custom") == "Custom"


def test_night_mode_switch_reports_state(coordinator: TronbytCoordinator):
    """Validate the night mode switch state and metadata."""
    entity = switch_mod.TronbytNightModeSwitch(coordinator, "dev1")
    info = entity.device_info
    assert info["identifiers"] == {(DOMAIN, "dev1")}
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_night_mode_switch_updates_both_flags(coordinator: TronbytCoordinator):
    """Switch updates should send both night mode and legacy auto dim flags."""
    entity = switch_mod.TronbytNightModeSwitch(coordinator, "dev1")
    coordinator.async_patch_device = AsyncMock()

    await entity.async_turn_off()
    coordinator.async_patch_device.assert_awaited_once_with(
        "dev1",
        {"nightModeEnabled": False, "autoDim": False},
    )


def test_installation_switch_name_and_state(coordinator: TronbytCoordinator):
    """Ensure installation switches include the hyphenated label."""
    entity = switch_mod.TronbytInstallationSwitch(coordinator, "dev1", "477")
    assert entity.name == "Enable Custom Clock-477"
    assert entity.is_on is True


@pytest.mark.asyncio
async def test_installation_switch_toggles_installation(
    coordinator: TronbytCoordinator,
):
    """Switch toggles should call the installation PATCH helper."""
    entity = switch_mod.TronbytInstallationSwitch(coordinator, "dev1", "217")
    coordinator.async_patch_installation = AsyncMock()

    await entity.async_turn_on()
    coordinator.async_patch_installation.assert_awaited_once_with(
        "dev1", "217", {"enabled": True}
    )

    coordinator.async_patch_installation.reset_mock()
    await entity.async_turn_off()
    coordinator.async_patch_installation.assert_awaited_once_with(
        "dev1", "217", {"enabled": False}
    )
