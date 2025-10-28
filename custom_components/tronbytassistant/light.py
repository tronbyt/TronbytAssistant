from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Optional

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)

BRIGHTNESS_MAX = 255
BRIGHTNESS_MIN = 0
BRIGHTNESS_API_MAX = 100


def _value_from_device(device: dict[str, Any], path: list[str]) -> Optional[int]:
    current: Any = device
    for key in path:
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            return None
    if current is None:
        return None
    try:
        return int(current)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TronbytLightDescription:
    key: str
    name: str
    icon: str | None
    value_path: list[str]
    patch_key: str
    default_on: int = BRIGHTNESS_MAX
    entity_category: EntityCategory | None = EntityCategory.CONFIG


LIGHT_DESCRIPTIONS: tuple[TronbytLightDescription, ...] = (
    TronbytLightDescription(
        key="brightness",
        name="Brightness",
        icon="mdi:television-ambient-light",
        value_path=["brightness"],
        patch_key="brightness",
    ),
    TronbytLightDescription(
        key="night_mode_brightness",
        name="Night Mode Brightness",
        icon="mdi:brightness-6",
        value_path=["night_mode", "brightness"],
        patch_key="nightModeBrightness",
        default_on=128,
    ),
    TronbytLightDescription(
        key="dim_mode_brightness",
        name="Dim Mode Brightness",
        icon="mdi:brightness-4",
        value_path=["dim_mode", "brightness"],
        patch_key="dimModeBrightness",
        default_on=128,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        _LOGGER.debug("No Tronbyt devices available; skipping light setup.")
        return

    entities: list[TronbytLight] = []
    for description in LIGHT_DESCRIPTIONS:
        for device in coordinator.data:
            device_id = device.get("id")
            if device_id is None:
                continue
            entities.append(TronbytLight(coordinator, device_id, description))

    if entities:
        async_add_entities(entities)


class TronbytLight(CoordinatorEntity, LightEntity):
    """Brightness style light bound to a Tronbyt device attribute."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytLightDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._deviceid = device_id
        self._attr_unique_id = f"tronbyt-{description.key}-{device_id}"
        self._attr_icon = description.icon
        self._attr_name = description.name
        self._attr_entity_category = description.entity_category

    def _device(self) -> Optional[dict[str, Any]]:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def brightness(self) -> int | None:
        device = self._device()
        if not device:
            return None
        value = _value_from_device(device, self._description.value_path)
        if value is None:
            return None
        value = max(0, min(BRIGHTNESS_API_MAX, value))
        return int(round((value / BRIGHTNESS_API_MAX) * BRIGHTNESS_MAX))

    @property
    def is_on(self) -> bool | None:
        value = self.brightness
        if value is None:
            return None
        return value > 0

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
        if ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS])
        else:
            brightness = self.brightness
            if brightness is None:
                brightness = self._description.default_on

        brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))
        api_value = int(round((brightness / BRIGHTNESS_MAX) * BRIGHTNESS_API_MAX))
        await self.coordinator.async_patch_device(
            self._deviceid,
            {self._description.patch_key: api_value},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_patch_device(
            self._deviceid,
            {self._description.patch_key: 0},
        )
