from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        _LOGGER.debug("No Tronbyt devices available; skipping switch setup.")
        return

    entities = [
        TronbytNightModeSwitch(coordinator, device["id"])
        for device in coordinator.data
        if device.get("id")
    ]
    if entities:
        async_add_entities(entities)


class TronbytNightModeSwitch(CoordinatorEntity, SwitchEntity):
    """Expose the Tronbyt night mode flag as a switch."""

    _attr_has_entity_name = True
    _attr_name = "Night Mode"
    _attr_icon = "mdi:brightness-auto"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._deviceid = device_id
        self._attr_unique_id = f"tronbytnightmode-{device_id}"

    def _device(self) -> Optional[dict[str, Any]]:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def is_on(self) -> bool | None:
        device = self._device()
        if not device:
            return None
        night = device.get("night_mode") or {}
        if night.get("enabled") is not None:
            return night.get("enabled")
        return device.get("auto_dim")

    @property
    def device_info(self) -> dict[str, Any]:
        device = self._device() or {}
        model = device.get("type") or "Display"
        name = device.get("name", self._deviceid)
        return {
            "identifiers": {(DOMAIN, self._deviceid)},
            "name": name,
            "manufacturer": "Tronbyt",
            "model": model,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_night_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_night_mode(False)

    async def _async_set_night_mode(self, enabled: bool) -> None:
        await self.coordinator.async_patch_device(
            self._deviceid,
            {
                "nightModeEnabled": enabled,
                "autoDim": enabled,
            },
        )
