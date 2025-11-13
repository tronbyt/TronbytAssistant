from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .device import build_device_info

NONE_OPTION = "none"


@dataclass(frozen=True)
class TronbytSelectDescription:
    key: str
    translation_key: str | None
    icon: str | None
    value_fn: Callable[[dict[str, Any]], Optional[str]]
    patch_key: str
    allow_none: bool = True
    entity_registry_enabled_default: bool = True
    entity_category: EntityCategory | None = EntityCategory.CONFIG


SELECT_DESCRIPTIONS: tuple[TronbytSelectDescription, ...] = (
    TronbytSelectDescription(
        key="night_mode_app",
        translation_key="night_mode_app",
        icon="mdi:application",
        value_fn=lambda device: (device.get("night_mode") or {}).get("app"),
        patch_key="nightModeApp",
    ),
    TronbytSelectDescription(
        key="pinned_app",
        translation_key="pinned_app",
        icon="mdi:pin",
        value_fn=lambda device: device.get("pinned_app"),
        patch_key="pinnedApp",
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

    entities: list[TronbytSelect] = []
    for description in SELECT_DESCRIPTIONS:
        for device in coordinator.data:
            device_id = device.get("id")
            if device_id is None:
                continue
            entities.append(TronbytSelect(coordinator, device_id, description))

    if entities:
        async_add_entities(entities)


class TronbytSelect(CoordinatorEntity, SelectEntity):
    """Select entity exposing Tronbyt device installations."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytSelectDescription,
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
        self._attr_device_class = None

    def _device(self) -> Optional[dict[str, Any]]:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def options(self) -> list[str]:
        device = self._device()
        if not device:
            return []
        installs = device.get("installations") or []
        seen: set[str] = set()
        options: list[str] = []
        for install in installs:
            app_id = install.get("appID")
            install_id = install.get("id")
            if not install_id or install_id in seen:
                continue
            seen.add(install_id)
            label = app_id or ""
            if label:
                options.append(f"{label}-{install_id}")
            else:
                options.append(str(install_id))
        options.sort()
        if self._description.allow_none:
            return [NONE_OPTION] + options
        return options

    @property
    def current_option(self) -> str | None:
        device = self._device()
        if not device:
            return None
        value = self._normalize_value(self._description.value_fn(device))
        if value is None:
            return NONE_OPTION if self._description.allow_none else None
        installs = device.get("installations") or []
        for install in installs:
            install_id = install.get("id")
            app_id = install.get("appID")
            if not install_id:
                continue
            if install_id == value or app_id == value:
                label = app_id or ""
                return f"{label}-{install_id}" if label else str(install_id)
        return value

    async def async_select_option(self, option: str) -> None:
        if option == NONE_OPTION and self._description.allow_none:
            payload_value = ""
        else:
            payload_value = option.rsplit("-", 1)[-1].strip()
        await self.coordinator.async_patch_device(
            self._deviceid,
            {self._description.patch_key: payload_value},
        )

    @staticmethod
    def _normalize_value(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed or trimmed.lower() == NONE_OPTION:
            return None
        return trimmed

    @property
    def unit_of_measurement(self) -> str | None:  # type: ignore[override]
        return None

    @property
    def device_info(self) -> dict[str, Any]:
        return build_device_info(self._device(), self._deviceid)
