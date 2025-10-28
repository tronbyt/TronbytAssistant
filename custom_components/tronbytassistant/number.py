from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN


@dataclass(frozen=True)
class TronbytNumberDescription:
    key: str
    translation_key: str | None
    icon: str | None
    min_value: float
    max_value: float
    step: float
    value_fn: Callable[[dict[str, Any]], float | None]
    patch_key: str
    unit: str | None = None
    device_class: str | None = None
    entity_registry_enabled_default: bool = True
    entity_category: EntityCategory | None = None


NUMBER_DESCRIPTIONS: tuple[TronbytNumberDescription, ...] = (
    TronbytNumberDescription(
        key="interval",
        translation_key="update_interval",
        icon="mdi:timer-sand",
        min_value=1,
        max_value=3600,
        step=1,
        value_fn=lambda device: device.get("interval"),
        patch_key="intervalSec",
        unit="s",
        entity_category=EntityCategory.CONFIG,
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

    entities: list[TronbytNumber] = []
    for description in NUMBER_DESCRIPTIONS:
        for device in coordinator.data:
            device_id = device.get("id")
            if device_id is None:
                continue
            entities.append(TronbytNumber(coordinator, device_id, description))

    if entities:
        async_add_entities(entities)


class TronbytNumber(CoordinatorEntity, NumberEntity):
    """Configurable numeric value backed by the Tronbyt API."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._deviceid = device_id
        self._attr_unique_id = f"tronbyt-{description.key}-{device_id}"
        self._attr_icon = description.icon
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_translation_key = description.translation_key
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_entity_category = description.entity_category

    def _device(self) -> dict[str, Any] | None:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def native_value(self) -> float | None:
        device = self._device()
        if not device:
            return None
        value = self._description.value_fn(device)
        if value is None:
            return None
        return int(round(value))

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

    async def async_set_native_value(self, value: float) -> None:
        value = max(
            self._attr_native_min_value,
            min(self._attr_native_max_value, value),
        )
        await self.coordinator.async_patch_device(
            self._deviceid,
            {self._description.patch_key: int(value)},
        )
