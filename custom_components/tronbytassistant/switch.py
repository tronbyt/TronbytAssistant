from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DATA_COORDINATOR, DOMAIN
from .device import build_device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TronbytSwitchDescription:
    key: str
    translation_key: str | None
    icon: str | None
    value_fn: Callable[[dict[str, Any]], bool | None]
    patch_key: str
    entity_registry_enabled_default: bool = True
    entity_category: EntityCategory | None = EntityCategory.CONFIG


SWITCH_DESCRIPTIONS: tuple[TronbytSwitchDescription, ...] = (
    TronbytSwitchDescription(
        key="skip_display_version",
        translation_key="skip_display_version",
        icon="mdi:counter",
        value_fn=lambda device: (device.get("info") or {}).get("skip_display_version"),
        patch_key="skipDisplayVersion",
    ),
    TronbytSwitchDescription(
        key="ap_mode",
        translation_key="ap_mode",
        icon="mdi:access-point",
        value_fn=lambda device: (device.get("info") or {}).get("ap_mode"),
        patch_key="apMode",
    ),
    TronbytSwitchDescription(
        key="prefer_ipv6",
        translation_key="prefer_ipv6",
        icon="mdi:ip-network",
        value_fn=lambda device: (device.get("info") or {}).get("prefer_ipv6"),
        patch_key="preferIPv6",
    ),
    TronbytSwitchDescription(
        key="swap_colors",
        translation_key="swap_colors",
        icon="mdi:palette-swatch",
        value_fn=lambda device: (device.get("info") or {}).get("swap_colors"),
        patch_key="swapColors",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data.get(DOMAIN, {}).get(DATA_COORDINATOR)
    if coordinator is None or not coordinator.data:
        _LOGGER.debug("No Tronbyt devices available; skipping switch setup.")
        return

    entities: list[SwitchEntity] = []
    for device in coordinator.data:
        device_id = device.get("id")
        if not device_id:
            continue
        entities.append(TronbytNightModeSwitch(coordinator, device_id))

        for description in SWITCH_DESCRIPTIONS:
            entities.append(TronbytFirmwareSwitch(coordinator, device_id, description))

        for install in device.get("installations") or []:
            install_id = install.get("id")
            if not install_id:
                continue
            entities.append(
                TronbytInstallationSwitch(coordinator, device_id, install_id)
            )

    if entities:
        async_add_entities(entities)


class TronbytNightModeSwitch(CoordinatorEntity, SwitchEntity):
    """Expose the Tronbyt night mode flag as a switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-auto"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "night_mode_switch"

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
        return build_device_info(self._device(), self._deviceid)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_night_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_night_mode(False)

    async def _async_set_night_mode(self, enabled: bool) -> None:
        await self.coordinator.async_patch_device(
            self._deviceid,
            {"nightModeEnabled": enabled},
        )


class TronbytInstallationSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to toggle an individual installation."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "installation_switch"

    def __init__(self, coordinator, device_id: str, installation_id: str) -> None:
        super().__init__(coordinator)
        self._deviceid = device_id
        self._installid = installation_id
        self._attr_unique_id = f"tronbytinstall-{device_id}-{installation_id}"

    def _device(self) -> Optional[dict[str, Any]]:
        for device in self.coordinator.data or []:
            if device.get("id") == self._deviceid:
                return device
        return None

    def _installation(self) -> Optional[dict[str, Any]]:
        device = self._device()
        if not device:
            return None
        for install in device.get("installations") or []:
            if install.get("id") == self._installid:
                return install
        return None

    @property
    def available(self) -> bool:
        return self._installation() is not None

    @property
    def is_on(self) -> bool | None:
        install = self._installation()
        if not install:
            return None
        return bool(install.get("enabled"))

    def _display_label(self) -> str:
        install = self._installation()
        if install:
            label = (install.get("appID") or "").strip()
            if label:
                return f"{label}-{self._installid}"
        return str(self._installid)

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"label": self._display_label()}

    @property
    def name(self) -> str | None:
        if getattr(self, "platform_data", None) is None:
            return f"Enable {self._display_label()}"
        return super().name

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_patch_installation(
            self._deviceid,
            self._installid,
            {"enabled": True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_patch_installation(
            self._deviceid,
            self._installid,
            {"enabled": False},
        )

    @property
    def device_info(self) -> dict[str, Any]:
        return build_device_info(self._device(), self._deviceid)


class TronbytFirmwareSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for Tronbyt firmware settings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_id: str,
        description: TronbytSwitchDescription,
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
    def is_on(self) -> bool | None:
        device = self._device()
        if not device:
            return None
        return self._description.value_fn(device)

    @property
    def device_info(self) -> dict[str, Any]:
        return build_device_info(self._device(), self._deviceid)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_firmware_settings(
            self._deviceid,
            {self._description.patch_key: True},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_firmware_settings(
            self._deviceid,
            {self._description.patch_key: False},
        )
