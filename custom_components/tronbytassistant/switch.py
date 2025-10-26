from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tronbyt auto-dim switches from a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        _LOGGER.debug("No Tronbyt devices available; skipping switch setup.")
        return

    entities = [
        TronbytAutoDimSwitch(coordinator, device["id"])
        for device in coordinator.data
        if device.get("id")
    ]
    if entities:
        async_add_entities(entities)


class TronbytAutoDimSwitch(CoordinatorEntity, SwitchEntity):
    """Expose the Tronbyt auto-dim flag as a switch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._deviceid = device_id
        self._attr_unique_id = f"tronbytautodim-{device_id}"

    @property
    def _device(self) -> Optional[dict[str, Any]]:
        if not self.coordinator.data:
            return None
        for device in self.coordinator.data:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def name(self) -> str:
        device = self._device
        display_name = device.get("name") if device else self._deviceid
        return f"{display_name} AutoDim"

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if not device:
            return None
        return device.get("autoDim")

    @property
    def available(self) -> bool:
        return self._device is not None

    @property
    def icon(self) -> str:
        return "mdi:brightness-auto"

    @property
    def device_info(self) -> dict[str, Any]:
        device = self._device or {}
        name = device.get("name", self._deviceid)
        return {
            "identifiers": {(DOMAIN, self._deviceid)},
            "name": name,
            "manufacturer": "Tronbyt",
            "model": "Display",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_autodim(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_autodim(False)

    async def _async_set_autodim(self, enabled: bool) -> None:
        session = async_get_clientsession(self.hass)
        url = f"{self.coordinator.base_url}/v0/devices/{self._deviceid}"
        headers = {
            "Authorization": f"Bearer {self.coordinator.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"autoDim": enabled}
        async with session.patch(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error = await response.text()
                _LOGGER.error("Failed to set autoDim on %s: %s", self._deviceid, error)
                return

        await self.coordinator.async_request_refresh()
