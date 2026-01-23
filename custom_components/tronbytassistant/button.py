from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DATA_COORDINATOR, DOMAIN
from .device import build_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        return

    entities: list[TronbytButton] = []
    for device in coordinator.data:
        device_id = device.get("id")
        if device_id:
            entities.append(TronbytButton(coordinator, device_id))

    if entities:
        async_add_entities(entities)


class TronbytButton(CoordinatorEntity, ButtonEntity):
    """Button to reboot the Tronbyt device."""

    _attr_has_entity_name = True
    _attr_translation_key = "reboot_button"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = "restart"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._deviceid = device_id
        self._attr_unique_id = f"tronbyt-reboot-{device_id}"

    def _device(self) -> dict[str, Any] | None:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def device_info(self) -> dict[str, Any]:
        return build_device_info(self._device(), self._deviceid)

    async def async_press(self) -> None:
        await self.coordinator.async_reboot_device(self._deviceid)
