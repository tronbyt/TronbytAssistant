from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .device import build_device_info


@dataclass(frozen=True)
class TronbytTextDescription:
    key: str
    translation_key: str | None
    icon: str | None
    value_fn: Callable[[dict[str, Any]], str | None]
    patch_key: str
    entity_registry_enabled_default: bool = True
    entity_category: EntityCategory | None = EntityCategory.CONFIG


TEXT_DESCRIPTIONS: tuple[TronbytTextDescription, ...] = (
    TronbytTextDescription(
        key="ssid",
        translation_key="ssid",
        icon="mdi:wifi",
        value_fn=lambda device: (device.get("info") or {}).get("ssid"),
        patch_key="ssid",
    ),
    TronbytTextDescription(
        key="image_url",
        translation_key="image_url",
        icon="mdi:image",
        value_fn=lambda device: (device.get("info") or {}).get("image_url"),
        patch_key="imageUrl",
    ),
    TronbytTextDescription(
        key="hostname",
        translation_key="hostname",
        icon="mdi:rename-box",
        value_fn=lambda device: (device.get("info") or {}).get("hostname"),
        patch_key="hostname",
    ),
    TronbytTextDescription(
        key="sntp_server",
        translation_key="sntp_server",
        icon="mdi:clock-time-four-outline",
        value_fn=lambda device: (device.get("info") or {}).get("sntp_server"),
        patch_key="sntpServer",
    ),
    TronbytTextDescription(
        key="syslog_addr",
        translation_key="syslog_addr",
        icon="mdi:file-document-outline",
        value_fn=lambda device: (device.get("info") or {}).get("syslog_addr"),
        patch_key="syslogAddr",
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

    entities: list[TronbytText] = []
    for description in TEXT_DESCRIPTIONS:
        for device in coordinator.data:
            device_id = device.get("id")
            if device_id is None:
                continue
            entities.append(TronbytText(coordinator, device_id, description))

    if entities:
        async_add_entities(entities)


class TronbytText(CoordinatorEntity, TextEntity):
    """Configurable text value backed by the Tronbyt API."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytTextDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._deviceid = device_id
        self._attr_unique_id = f"tronbyt-{description.key}-{device_id}"
        self._attr_icon = description.icon
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
    def native_value(self) -> str | None:
        device = self._device()
        if not device:
            return None
        return self._description.value_fn(device)

    @property
    def device_info(self) -> dict[str, Any]:
        return build_device_info(self._device(), self._deviceid)

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_update_firmware_settings(
            self._deviceid,
            {self._description.patch_key: value},
        )
