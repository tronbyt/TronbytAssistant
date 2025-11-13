from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import DOMAIN


def build_device_info(
    device: dict[str, Any] | None,
    device_id: str,
) -> dict[str, Any]:
    """Return a Home Assistant device registry payload for a Tronbyt device."""

    device = device or {}
    info = device.get("info") or {}

    payload: dict[str, Any] = {
        "identifiers": {(DOMAIN, device_id)},
        "name": device.get("name") or device_id,
        "manufacturer": "Tronbyt",
        "model": device.get("type") or "Display",
    }

    firmware = info.get("firmware_version")
    if firmware:
        payload["sw_version"] = firmware

    hardware = info.get("firmware_type")
    if hardware:
        payload["hw_version"] = hardware

    mac_address = info.get("mac_address")
    if mac_address:
        payload["connections"] = {
            (CONNECTION_NETWORK_MAC, str(mac_address).lower()),
        }

    return payload
