from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any, Callable

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DATA_COORDINATOR, DOMAIN


@dataclass(frozen=True)
class TronbytTimeDescription:
    key: str
    translation_key: str | None
    icon: str | None
    value_fn: Callable[[dict[str, Any]], str | None]
    patch_key: str
    entity_registry_enabled_default: bool = True
    entity_category: EntityCategory | None = EntityCategory.CONFIG


TIME_DESCRIPTIONS: tuple[TronbytTimeDescription, ...] = (
    TronbytTimeDescription(
        key="night_mode_start",
        translation_key="night_mode_start",
        icon="mdi:weather-night",
        value_fn=lambda device: (device.get("night_mode") or {}).get("start"),
        patch_key="nightModeStartTime",
    ),
    TronbytTimeDescription(
        key="night_mode_end",
        translation_key="night_mode_end",
        icon="mdi:weather-sunset-up",
        value_fn=lambda device: (device.get("night_mode") or {}).get("end"),
        patch_key="nightModeEndTime",
    ),
    TronbytTimeDescription(
        key="dim_mode_start",
        translation_key="dim_mode_start",
        icon="mdi:weather-sunset-down",
        value_fn=lambda device: (device.get("dim_mode") or {}).get("start"),
        patch_key="dimModeStartTime",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        return

    entities: list[TronbytTime] = []
    for description in TIME_DESCRIPTIONS:
        for device in coordinator.data:
            device_id = device.get("id")
            if device_id is None:
                continue
            entities.append(TronbytTime(coordinator, device_id, description))

    if entities:
        async_add_entities(entities)


class TronbytTime(CoordinatorEntity, TimeEntity):
    """Time configuration for Tronbyt schedules."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytTimeDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._deviceid = device_id
        self._attr_unique_id = f"tronbyt-{description.key}-{device_id}"
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_translation_key = description.translation_key
        self._attr_entity_category = description.entity_category
        self._attr_native_unit_of_measurement = None

    def _device(self) -> dict[str, Any] | None:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    def _current_value(self) -> str | None:
        device = self._device()
        if not device:
            return None
        return self._description.value_fn(device)

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def native_unit_of_measurement(self) -> str | None:
        return None

    @property
    def native_value(self) -> time | None:
        raw = self._current_value()
        if not raw:
            return None
        try:
            parts = raw.split(":")
            if len(parts) == 2:
                hour, minute = parts
                second = 0
            elif len(parts) == 3:
                hour, minute, second = parts
            else:
                return None
            return time(int(hour), int(minute), int(second))
        except (ValueError, TypeError):
            return None

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

    async def async_set_value(self, value: time | None) -> None:
        if value is None:
            payload_value = ""
        else:
            payload_value = value.strftime("%H:%M")

        await self.coordinator.async_patch_device(
            self._deviceid,
            {self._description.patch_key: payload_value},
        )
